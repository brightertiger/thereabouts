"""Convert frozen division row groups using a freshly regenerated parent index."""

import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import shapely

from pipeline.pins.models import PinFile
from pipeline.runtime.jsonio import atomic_output, digest, encode, write_json
from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.geometry import GeometryError
from pipeline.sources.shared.manifest import finish
from pipeline.sources.shared.schemas import Kind
from pipeline.sources.shared.writer import PartitionWriter

from .areas import areas
from .index import build_index
from .rows import RowRejectedError, names, place


def group(
    ctx: SourceContext,
    pin: PinFile,
    parquet: pq.ParquetFile,
    ordinal: int,
    db: sqlite3.Connection,
) -> tuple[list[Path], list[Path]]:
    key = f"{pin.name}#row-group={ordinal}"
    kind: Kind = "places" if pin.metadata["type"] == "division" else "areas"
    sink, aliases = PartitionWriter(ctx, kind, key), PartitionWriter(ctx, "names", key)
    root = ctx.normalized / "audits" / ctx.inputs_hash
    audit_path = root / f"{digest(key)}.json"
    ctx.ensure(audit_path)
    rejects = ctx.ensure(audit_path.with_suffix(".jsonl"))
    stats: Counter[str] = Counter()
    subtypes: Counter[str] = Counter()
    context: dict[str, Any] = {
        "source_release": ctx.pin.release,
        "source_url": pin.url,
        "input_sha256": pin.sha256,
        "license": ctx.settings.licence.id,
        "license_url": ctx.settings.licence.url,
        "attribution": ctx.settings.licence.attribution,
        "row_group": ordinal,
    }
    options = ctx.settings.options
    batch_size = int(
        options["point_batch_rows"] if kind == "places" else options["area_batch_rows"]
    )
    with atomic_output(rejects) as temporary, temporary.open("wb") as audit:
        for batch in parquet.iter_batches(
            batch_size=batch_size, row_groups=[ordinal], use_threads=False
        ):
            ctx.guard.admit()
            for row in batch.to_pylist():
                stats["input_rows"] += 1
                subtypes[row["subtype"]] += 1
                row_context = {**context, "row_in_group": stats["input_rows"] - 1}
                before = sink.count
                try:
                    if kind == "places":
                        converted = place(row, row_context)
                        converted_aliases = list(names(row, row_context))
                        sink.add(converted)
                        stats["valid_input"] += 1
                        for alias in converted_aliases:
                            aliases.add(alias)
                    else:
                        entity = db.execute(
                            "SELECT parent FROM entities WHERE id=?",
                            (row["division_id"],),
                        ).fetchone()
                        if entity is None:
                            stats["missing_division_ids"] += 1
                        for area in areas(
                            row,
                            row_context,
                            entity[0] if entity else None,
                            stats,
                            int(options["geometry_bytes"]),
                            int(options["geometry_max_depth"]),
                        ):
                            sink.add(area)
                    stats["accepted_features"] += 1
                except (
                    RowRejectedError,
                    GeometryError,
                    shapely.errors.GEOSException,
                ) as error:
                    if sink.count != before:
                        raise ValueError(
                            f"Partial feature conversion: {row['id']}"
                        ) from error
                    stats["rejected_features"] += 1
                    audit.write(
                        encode(
                            {
                                "id": row["id"],
                                "row_in_group": stats["input_rows"] - 1,
                                "reason": str(error),
                            }
                        )
                        + b"\n"
                    )
    expected = parquet.metadata.row_group(ordinal).num_rows
    if (
        stats["input_rows"] != expected
        or stats["accepted_features"] + stats["rejected_features"] != expected
    ):
        raise ValueError("Overture row-group source count mismatch")
    outputs = [*sink.finish(), *aliases.finish()]
    write_json(
        audit_path,
        {
            "unit": key,
            "counts": dict(stats),
            "subtypes": dict(subtypes),
            "output_rows": {kind: sink.count, "names": aliases.count},
        },
    )
    return outputs, [audit_path, rejects]


def normalize(ctx: SourceContext) -> list[Path]:
    index = build_index(ctx)
    outputs: list[Path] = []
    auxiliary = [index]
    with closing(
        sqlite3.connect(f"{index.absolute().as_uri()}?mode=ro&immutable=1", uri=True)
    ) as db:
        db.execute(
            f"PRAGMA cache_size=-{int(ctx.settings.options['sqlite_cache_kib'])}"
        )
        for pin in ctx.pin.files:
            with pq.ParquetFile(ctx.input(pin.name)) as parquet:
                for ordinal in range(parquet.num_row_groups):
                    paths, audits = group(ctx, pin, parquet, ordinal, db)
                    outputs.extend(paths)
                    auxiliary.extend(audits)
    return finish(ctx, outputs, auxiliary)
