"""Stream selected GeoNames features and aliases with rejection evidence."""

import base64
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import BinaryIO, cast

from pipeline.files import sqlite_readonly
from pipeline.runtime.jsonio import atomic_output, write_json
from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.manifest import finish
from pipeline.sources.shared.rows import RowRejected, canonical_json
from pipeline.sources.shared.schemas import Kind
from pipeline.sources.shared.writer import PartitionWriter

from .index import build_index
from .inputs import evidence, inputs
from .rows import Row, alias, place
from .tsv import chunks, lines


def reject(target: BinaryIO, offset: int, raw: bytes, error: str) -> None:
    record = {
        "byte_offset": offset,
        "reason": error,
        "raw_base64": base64.b64encode(raw).decode("ascii"),
    }
    # json.dumps defaults: spaced separators, ASCII escapes, insertion order.
    line = canonical_json(
        record, sort_keys=False, separators=None, ensure_ascii=True, allow_nan=True
    )
    target.write((line + "\n").encode())


def normalized_row(
    kind: Kind, raw: bytes, offset: int, db: sqlite3.Connection, release: str, pin: Row
) -> Row | None:
    if kind == "places":
        row = place(raw, release, pin)
        if row is None:
            return None
        indexed = db.execute(
            "SELECT offset FROM features WHERE id=?", (row["source_id"],)
        ).fetchone()
        if indexed != (offset,):
            raise RowRejected("Duplicate feature ID")
        english = db.execute(
            "SELECT name, alias_id FROM english WHERE id=?", (row["source_id"],)
        ).fetchone()
        if english:
            row["name_en"] = english[0]
            evidence = cast(Row, json.loads(str(row["provenance"])))
            evidence["name_en_alternate_id"] = str(english[1])
            evidence["name_en_language"] = "en"
            row["provenance"] = canonical_json(
                evidence, sort_keys=False, allow_nan=True
            )
        return row
    row = alias(raw, release, pin)
    if (
        db.execute(
            "SELECT 1 FROM features WHERE id=?", (row["entity_source_id"],)
        ).fetchone()
        is None
    ):
        return None
    indexed = db.execute(
        "SELECT offset FROM aliases WHERE id=?", (row["source_id"],)
    ).fetchone()
    if indexed != (offset,):
        raise RowRejected("Duplicate alternate-name ID")
    return row


def normalize(ctx: SourceContext) -> list[Path]:
    paths, auxiliary = inputs(ctx)
    index = build_index(ctx, paths)
    auxiliary.append(index)
    outputs: list[Path] = []
    reports: list[Row] = []
    root = ctx.normalized / "audits" / ctx.inputs_hash
    rejects = ctx.ensure(root / "rejects.jsonl")
    options = ctx.settings.options
    with (
        closing(sqlite_readonly(index, int(options["sqlite_cache_kib"]))) as db,
        atomic_output(rejects) as temporary,
        temporary.open("wb") as audit,
    ):
        for kind, member, archive in (
            ("places", "allCountries.txt", "allCountries.zip"),
            ("names", "alternateNamesV2.txt", "alternateNamesV2.zip"),
        ):
            family = cast(Kind, kind)
            pin = evidence(ctx, ctx.named(archive))
            writer = PartitionWriter(ctx, family, member)
            counts: Counter[str] = Counter()
            for chunk in chunks(
                paths[member],
                ctx.settings.limits.chunk_bytes,
                int(options["line_bytes"]),
            ):
                ctx.guard.admit()
                for offset, raw in lines(
                    paths[member], chunk, int(options["line_bytes"])
                ):
                    counts["input"] += 1
                    try:
                        row = normalized_row(
                            family, raw, offset, db, ctx.pin.release, pin
                        )
                    except (ValueError, UnicodeError, OverflowError) as error:
                        counts["rejected"] += 1
                        reject(audit, offset, raw, str(error))
                        continue
                    if row is None:
                        counts["excluded"] += 1
                    else:
                        writer.add(row)
                        counts["kept"] += 1
            if (
                counts["input"]
                != counts["kept"] + counts["excluded"] + counts["rejected"]
            ):
                raise ValueError("Unaccounted GeoNames input rows")
            outputs.extend(writer.finish())
            reports.append({"kind": kind, "counts": dict(counts)})
    report = ctx.ensure(root / "report.json")
    write_json(report, {"inputs": reports})
    return finish(ctx, outputs, [*auxiliary, rejects, report])
