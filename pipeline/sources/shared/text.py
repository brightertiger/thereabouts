"""Stream independently parsed text records into the common source contract."""

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.pins.models import PinFile
from pipeline.runtime.jsonio import atomic_output, encode, write_json
from pipeline.sources.contract import SourceContext

from .lookup_rows import Row, decorate
from .manifest import finish
from .rows import RowRejected
from .schemas import Kind
from .writer import PartitionWriter


@dataclass(frozen=True)
class InputRow:
    kind: Kind
    pin: PinFile
    ordinal: int
    raw: Row


def publish_rows(
    ctx: SourceContext, records: Iterable[InputRow], convert: Callable[[InputRow], Row]
) -> list[Path]:
    writers: dict[Kind, PartitionWriter] = {}
    counts: Counter[str] = Counter()
    report_root = ctx.normalized / "audits" / ctx.inputs_hash
    ctx.ensure(report_root).mkdir(parents=True, exist_ok=True)
    rejects_path = ctx.ensure(report_root / "rejects.jsonl")
    # Rejection evidence is streamed too; bad input cannot fill process memory.
    with atomic_output(rejects_path) as temporary, temporary.open("wb") as rejects:
        for item in records:
            counts["input"] += 1
            key = str(item.pin.metadata.get("key", item.pin.name))
            try:
                row = convert(item)
            except RowRejected as error:
                counts["rejected"] += 1
                rejects.write(
                    encode(
                        {
                            "file": key,
                            "record": item.ordinal,
                            "reason": str(error),
                            "raw": item.raw,
                        }
                    )
                    + b"\n"
                )
                continue
            pin: dict[str, Any] = {
                "url": item.pin.url,
                "license": ctx.settings.licence.id,
                "license_url": ctx.settings.licence.url,
                "attribution": ctx.settings.licence.attribution,
                "retrieved_at": ctx.pin.pinned_at,
                **item.pin.metadata,
            }
            row = decorate(
                row,
                ctx.settings.name,
                f"{key}:{item.ordinal}",
                pin,
                ctx.pin.release,
                item.raw,
            )
            if item.kind not in writers:
                writers[item.kind] = PartitionWriter(ctx, item.kind, "records")
            writer = writers[item.kind]
            writer.add(row)
            counts["retained"] += 1
        partitions = [path for writer in writers.values() for path in writer.finish()]
    report = ctx.ensure(report_root / "report.json")
    write_json(
        report,
        {
            "counts": dict(counts),
            "rows": {kind: writer.count for kind, writer in writers.items()},
        },
    )
    return finish(ctx, partitions, [report, rejects_path])
