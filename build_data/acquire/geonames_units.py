"""Geonames units."""

from __future__ import annotations

import base64
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path
from typing import BinaryIO, cast

import pyarrow.parquet as pq

from . import Ledger, Workspace, atomic_output, fingerprint
from .geonames_download import SOURCE, read_json
from .geonames_rows import Row, alias, place
from .geonames_settings import BATCH_BYTES, BATCH_ROWS, PARTITION_BYTES, SPOTS, STAGE
from .geonames_tsv import Chunk, fields, lines
from .io import write_json
from .runtime import source_budget
from .schemas import Kind
from .writer import PartitionWriter


def _reject(target: BinaryIO, offset: int, raw: bytes, error: str) -> None:
    target.write(
        (
            json.dumps(
                {
                    "byte_offset": offset,
                    "reason": error,
                    "raw_base64": base64.b64encode(raw).decode("ascii"),
                }
            )
            + "\n"
        ).encode()
    )


def _normalized_row(
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
            raise ValueError("Duplicate feature ID")
        english = db.execute(
            "SELECT name, alias_id FROM english WHERE id=?", (row["source_id"],)
        ).fetchone()
        if english:
            row["name_en"] = english[0]
            evidence = cast(Row, json.loads(str(row["provenance"])))
            evidence["name_en_alternate_id"] = str(english[1])
            evidence["name_en_language"] = "en"
            row["provenance"] = json.dumps(
                evidence, ensure_ascii=False, separators=(",", ":")
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
        raise ValueError("Duplicate alternate-name ID")
    return row


def normalize_chunk(
    workspace: Workspace,
    path: Path,
    chunk: Chunk,
    kind: Kind,
    db: sqlite3.Connection,
    inventory: Row,
    digest: str,
) -> tuple[Row, Path]:
    unit = f"{path.name}:{chunk.start}-{chunk.end}"
    unit_hash = fingerprint({"build": digest, "unit": unit, "kind": kind})
    reference: Row = {"stage": STAGE, "unit_id": unit, "inputs_hash": unit_hash}
    report = workspace.work / SOURCE / digest / f"{unit}.json"
    rejects = report.with_suffix(".rejects.jsonl")
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete(STAGE, unit, unit_hash):
        return reference, report
    source_budget(workspace, SOURCE, 400_000_000)
    pins = cast(dict[str, Row], inventory["files"])
    pin = pins["allCountries.zip" if kind == "places" else "alternateNamesV2.zip"]
    writer = PartitionWriter(
        workspace,
        SOURCE,
        kind,
        unit,
        unit_hash,
        batch_rows=BATCH_ROWS,
        batch_bytes=BATCH_BYTES,
        part_bytes=PARTITION_BYTES,
        overhead=256,
        scalar_bytes=8,
    )
    counts: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    spots: dict[str, Row] = {}
    started = time.monotonic()
    with atomic_output(rejects, lambda p: None) as temp, temp.open("wb") as audit:
        for offset, raw in lines(path, chunk):
            counts["input"] += 1
            if kind == "places":
                try:
                    values = fields(raw, 19)
                    classes[values[6]] += 1
                except (ValueError, UnicodeError):
                    pass  # The full raw row is audited immediately below.
            try:
                row = _normalized_row(
                    kind, raw, offset, db, str(inventory["source_release"]), pin
                )
            except (ValueError, UnicodeError, OverflowError) as error:
                counts["rejected"] += 1
                errors[str(error)] += 1
                _reject(audit, offset, raw, str(error))
                continue
            if row is None:
                counts["excluded"] += 1
                continue
            writer.add(row)
            counts["kept"] += 1
            if kind == "places":
                codes[f"{row['feature_class']}.{row['feature_code']}"] += 1
                counts["valid_coordinates"] += 1
                counts["english_names"] += row["name_en"] is not None
                if str(row["source_id"]) in SPOTS:
                    spots[str(row["source_id"])] = row
            else:
                languages[str(row["language"] or "<unspecified>")] += 1
                for flag in (
                    "is_preferred",
                    "is_short",
                    "is_colloquial",
                    "is_historic",
                ):
                    counts[flag] += bool(row[flag])
    outputs = writer.finish()
    if counts["input"] != counts["kept"] + counts["excluded"] + counts["rejected"]:
        raise ValueError("Unaccounted input rows")
    written = sum(pq.ParquetFile(output).metadata.num_rows for output in outputs)
    if written != counts["kept"]:
        raise ValueError("Parquet row count differs from retained source lines")
    write_json(
        report,
        {
            "unit": unit,
            "kind": kind,
            "counts": dict(counts),
            "source_classes": dict(classes),
            "feature_codes": dict(codes),
            "languages": dict(languages),
            "errors": dict(errors),
            "spots": spots,
            "outputs": [str(p) for p in outputs],
            "output_bytes": sum(p.stat().st_size for p in outputs),
            "seconds": round(time.monotonic() - started, 3),
        },
    )
    ledger.complete(
        STAGE, unit, unit_hash, [*outputs, report, rejects], metadata=read_json(report)
    )
    print(f"Normalized {unit}: {dict(counts)}", flush=True)
    return reference, report
