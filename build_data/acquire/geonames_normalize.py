"""Bounded, checkpointed GeoNames extraction, indexes and Parquet publication."""

from __future__ import annotations

import base64
import json
import sqlite3
import time
import zipfile
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

import pyarrow as pa
import pyarrow.parquet as pq

from . import (
    SCHEMA_HASHES,
    SCHEMAS,
    Ledger,
    Workspace,
    atomic_output,
    fingerprint,
    sha256_file,
    write_partition,
)
from .geonames_download import FILES, SOURCE, budget, now, read_json, source_lock
from .geonames_rows import (
    BUILDER_VERSION,
    MAX_LINE_BYTES,
    POLICY_VERSION,
    Row,
    alias,
    english_rank,
    fields,
    place,
)
from .geonames_statistics import artifacts, comparison
from .io import publish, write_json
from .schemas import Kind

CHUNK_BYTES = 64 * 1024 * 1024
BATCH_ROWS = 4096
PARTITION_BYTES = 48_000_000
BATCH_BYTES = 12_000_000
READ_BYTES = 1024 * 1024
STAGE = "geonames.normalize"
SPOTS = {
    "2332459": ("Lagos", "NG", 1_000_000, 40_000_000),
    "1819729": ("Hong Kong", "HK", 1_000_000, 15_000_000),
    "1850147": ("Tokyo", "JP", 1_000_000, 50_000_000),
    "5128581": ("New York City", "US", 1_000_000, 30_000_000),
    "1880252": ("Singapore", "SG", 1_000_000, 10_000_000),
    "2993458": ("Monaco", "MC", 500, 100_000),
}


@dataclass(frozen=True)
class Chunk:
    start: int
    end: int


def chunks(path: Path) -> Iterator[Chunk]:
    """Find complete-line byte intervals without decoding or loading a TSV."""
    size = path.stat().st_size
    start = 0
    with path.open("rb") as stream:
        while start < size:
            stream.seek(min(size, start + CHUNK_BYTES))
            if stream.tell() < size:
                stream.readline(MAX_LINE_BYTES + 1)
            end = stream.tell()
            yield Chunk(start, end)
            start = end


def lines(path: Path, chunk: Chunk) -> Iterator[tuple[int, bytes]]:
    with path.open("rb") as stream:
        stream.seek(chunk.start)
        while stream.tell() < chunk.end:
            offset = stream.tell()
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError(f"Oversized raw TSV line at {path}:{offset}")
            yield offset, raw


def _extract_member(
    workspace: Workspace, archive: Path, member: str, pin: Mapping[str, object]
) -> Path:
    ledger = Ledger(workspace.ledger_path)
    key = f"extract/{archive.name}/{member}"
    digest = fingerprint(
        {"archive": pin["sha256"], "member": member, "builder": BUILDER_VERSION}
    )
    destination = workspace.work / SOURCE / "extracted" / digest / member
    outputs = ledger.completed_outputs("geonames.extract", key, digest)
    if outputs is not None:
        return outputs[0]
    if Path(member).name != member:
        raise ValueError(f"Unexpected nested or unsafe archive member: {member}")
    started = time.monotonic()
    with zipfile.ZipFile(archive) as zipped:
        info = zipped.getinfo(member)
        budget(workspace, info.file_size)
        with (
            atomic_output(
                destination, lambda path: _check_size(path, info.file_size)
            ) as temp,
            zipped.open(info) as source,
            temp.open("wb") as target,
        ):
            count, last = 0, b""
            while block := source.read(READ_BYTES):
                target.write(block)
                count += block.count(b"\n")
                last = block[-1:]
            count += bool(last and last != b"\n")
    report = destination.with_name(destination.name + ".json")
    write_json(
        report,
        {
            "member": member,
            "bytes": info.file_size,
            "crc32": info.CRC,
            "crc_valid": True,
            "lines": count,
            "sha256": sha256_file(destination),
            "seconds": round(time.monotonic() - started, 3),
        },
    )
    ledger.complete("geonames.extract", key, digest, [destination, report])
    print(f"Extracted {member}: {count:,} lines", flush=True)
    return destination


def _check_size(path: Path, expected: int) -> None:
    if path.stat().st_size != expected:
        raise ValueError(f"Extracted size mismatch: {path}")


def extract(workspace: Workspace, inventory: Row) -> dict[str, Path]:
    pins = cast(dict[str, Row], inventory["files"])
    result: dict[str, Path] = {}
    for name in FILES:
        pin = pins[name]
        path = Path(str(pin["path"]))
        if sha256_file(path) != pin["sha256"]:
            raise ValueError(f"Raw input checksum mismatch: {path}")
        if name.endswith(".zip"):
            with zipfile.ZipFile(path) as zipped:
                members = [
                    item.filename for item in zipped.infolist() if not item.is_dir()
                ]
            for member in members:
                result[member] = _extract_member(workspace, path, member, pin)
        else:
            result[name] = path
    return result


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro" if readonly else str(path), uri=readonly
    )
    db.execute("PRAGMA cache_size=-32768")
    db.execute("PRAGMA temp_store=FILE")
    if not readonly:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(
            "CREATE TABLE IF NOT EXISTS features "
            "(id INTEGER PRIMARY KEY, offset INTEGER);"
            "CREATE TABLE IF NOT EXISTS aliases "
            "(id INTEGER PRIMARY KEY, offset INTEGER);"
            "CREATE TABLE IF NOT EXISTS english (id INTEGER PRIMARY KEY, name TEXT, "
            "rank INTEGER, alias_id INTEGER);"
            "CREATE TABLE IF NOT EXISTS done (unit TEXT PRIMARY KEY, counts TEXT);"
        )
    return db


def _index_place(
    db: sqlite3.Connection, raw: bytes, offset: int, release: str, pin: Row
) -> str:
    row = place(raw, release, pin)
    if row is None:
        return "excluded"
    cursor = db.execute(
        "INSERT OR IGNORE INTO features VALUES (?, ?)", (row["source_id"], offset)
    )
    return "kept" if cursor.rowcount else "duplicate"


def _index_alias(
    db: sqlite3.Connection, raw: bytes, offset: int, release: str, pin: Row
) -> str:
    row = alias(raw, release, pin)
    entity = str(row["entity_source_id"])
    if db.execute("SELECT 1 FROM features WHERE id=?", (entity,)).fetchone() is None:
        return "excluded"
    if not db.execute(
        "INSERT OR IGNORE INTO aliases VALUES (?, ?)", (row["source_id"], offset)
    ).rowcount:
        return "duplicate"
    rank = english_rank(row)
    if rank is not None:
        db.execute(
            "INSERT INTO english VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, rank=excluded.rank, alias_id=excluded.alias_id "
            "WHERE (excluded.rank, excluded.alias_id) < "
            "(english.rank, english.alias_id)",
            (entity, row["name"], *rank),
        )
    return "kept"


def build_index(
    workspace: Workspace, inputs: Mapping[str, Path], inventory: Row, digest: str
) -> Path:
    """Commit each input interval in SQLite; publish the index only when complete."""
    path = workspace.work / SOURCE / digest / "lookup.sqlite3"
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete("geonames.index", "lookup", digest):
        return path
    budget(workspace, 1_000_000_000)
    part = path.with_suffix(".sqlite3.part")
    pins = cast(dict[str, Row], inventory["files"])
    with closing(_connect(part)) as db:
        for member, archive, parser in (
            ("allCountries.txt", "allCountries.zip", _index_place),
            ("alternateNamesV2.txt", "alternateNamesV2.zip", _index_alias),
        ):
            for chunk in chunks(inputs[member]):
                key = f"{member}:{chunk.start}-{chunk.end}"
                if db.execute("SELECT 1 FROM done WHERE unit=?", (key,)).fetchone():
                    continue
                budget(workspace, 150_000_000)
                counts: Counter[str] = Counter()
                with db:
                    for offset, raw in lines(inputs[member], chunk):
                        try:
                            state = parser(
                                db,
                                raw,
                                offset,
                                str(inventory["source_release"]),
                                pins[archive],
                            )
                        except (ValueError, UnicodeError, OverflowError):
                            state = "rejected"
                        counts[state] += 1
                    db.execute(
                        "INSERT INTO done VALUES (?, ?)", (key, json.dumps(counts))
                    )
                print(f"Indexed {key}: {dict(counts)}", flush=True)
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("GeoNames lookup integrity check failed")
    publish(part, path)
    ledger.complete("geonames.index", "lookup", digest, [path])
    return path


class Partitions:
    """Keep only a few small Arrow batches; shared writer validates each file."""

    def __init__(
        self, workspace: Workspace, kind: Kind, unit: str, digest: str
    ) -> None:
        self.workspace, self.kind, self.unit, self.digest = (
            workspace,
            kind,
            unit,
            digest,
        )
        self.rows: list[Row] = []
        self.estimated_bytes = 0
        self.tables: list[pa.Table] = []
        self.decoded_bytes = 0
        self.outputs: list[Path] = []
        self.count = 0

    def append(self, row: Row) -> None:
        estimate = (
            sum(
                len(value.encode("utf-8")) if isinstance(value, str) else 8
                for value in row.values()
            )
            + 256
        )
        if self.rows and (
            self.estimated_bytes + estimate > BATCH_BYTES
            or len(self.rows) >= BATCH_ROWS
        ):
            self.batch()
        self.rows.append(row)
        self.estimated_bytes += estimate
        self.count += 1

    def batch(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pylist(self.rows, schema=SCHEMAS[self.kind])
        if self.tables and self.decoded_bytes + table.nbytes > PARTITION_BYTES:
            self.flush()
        self.tables.append(table)
        self.decoded_bytes += table.nbytes
        self.rows = []
        self.estimated_bytes = 0

    def flush(self) -> None:
        if not self.tables:
            return
        path = self.workspace.partition(
            SOURCE, self.kind, self.unit, self.digest, part=len(self.outputs)
        )
        write_partition(path, self.kind, self.tables)
        self.outputs.append(path)
        self.tables = []
        self.decoded_bytes = 0

    def finish(self) -> list[Path]:
        self.batch()
        self.flush()
        return self.outputs


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
    budget(workspace, 400_000_000)
    pins = cast(dict[str, Row], inventory["files"])
    pin = pins["allCountries.zip" if kind == "places" else "alternateNamesV2.zip"]
    writer = Partitions(workspace, kind, unit, unit_hash)
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
            writer.append(row)
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


def summarize(
    reports: list[Path], inputs: Mapping[str, Path], db: sqlite3.Connection
) -> Row:
    totals = {"places": Counter[str](), "names": Counter[str]()}
    codes: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    spots: dict[str, Row] = {}
    output_bytes = 0
    unit_seconds = 0.0
    for path in reports:
        report = read_json(path)
        totals[str(report["kind"])].update(cast(dict[str, int], report["counts"]))
        codes.update(cast(dict[str, int], report["feature_codes"]))
        classes.update(cast(dict[str, int], report["source_classes"]))
        languages.update(cast(dict[str, int], report["languages"]))
        spots.update(cast(dict[str, Row], report["spots"]))
        output_bytes += int(str(report["output_bytes"]))
        unit_seconds += float(str(report["seconds"]))
    for kind, member, table in (
        ("places", "allCountries.txt", "features"),
        ("names", "alternateNamesV2.txt", "aliases"),
    ):
        extracted = inputs[member]
        source_lines = int(
            str(read_json(extracted.with_name(extracted.name + ".json"))["lines"])
        )
        if totals[kind]["input"] != source_lines:
            raise ValueError(f"Source line accounting mismatch: {kind}")
        expected = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if totals[kind]["kept"] != expected:
            raise ValueError(f"Unique-ID count mismatch: {kind}")
    checks: dict[str, Row] = {}
    for identifier, (name, country, low, high) in SPOTS.items():
        row = spots.get(identifier)
        checks[name] = {
            "source_id": identifier,
            "present": row is not None,
            "passed": bool(
                row
                and row["country_code"] == country
                and row["name_en"]
                and low <= int(str(row["population"])) <= high
            ),
            "row": row,
        }
    return {
        "counts": {kind: dict(counts) for kind, counts in totals.items()},
        "source_classes": dict(classes),
        "feature_codes": dict(codes),
        "languages": dict(languages),
        "spot_checks": checks,
        "spot_checks_passed": all(check["passed"] for check in checks.values()),
        "output_bytes": output_bytes,
        "unit_transform_seconds": round(unit_seconds, 3),
        "line_accounting_verified": True,
        "unique_ids_verified": True,
        "names_foreign_keys_verified": True,
        "geometry": "places use validated WGS84 coordinates; no polygon geometry",
        "excluded": "classes other than P/A; aliases whose entities were not retained",
        "publisher_counts": (
            "Daily export line counts are authoritative; "
            "live web statistics may differ."
        ),
    }


def normalize(workspace: Workspace) -> None:
    """Publish all P/A points and their aliases, with reproducible audit metadata."""
    with source_lock(workspace, "normalize"):
        started = time.monotonic()
        inventory = read_json(workspace.raw(SOURCE) / "inventory.json")
        if "completed_at" not in inventory:
            raise ValueError("GeoNames download is not complete")
        digest = fingerprint(
            {
                "inventory": inventory,
                "builder": BUILDER_VERSION,
                "policy": POLICY_VERSION,
                "schemas": SCHEMA_HASHES,
                "chunk_bytes": CHUNK_BYTES,
                "max_line_bytes": MAX_LINE_BYTES,
                "batch_rows": BATCH_ROWS,
                "partition_bytes": PARTITION_BYTES,
            }
        )
        inputs = extract(workspace, inventory)
        index = build_index(workspace, inputs, inventory, digest)
        units: list[Row] = []
        reports: list[Path] = []
        with closing(_connect(index, readonly=True)) as db:
            for kind, member in (
                ("places", "allCountries.txt"),
                ("names", "alternateNamesV2.txt"),
            ):
                for chunk in chunks(inputs[member]):
                    unit, report = normalize_chunk(
                        workspace,
                        inputs[member],
                        chunk,
                        cast(Kind, kind),
                        db,
                        inventory,
                        digest,
                    )
                    units.append(unit)
                    reports.append(report)
            verification = summarize(reports, inputs, db)
        verification["publisher_statistics"] = comparison(
            workspace,
            cast(dict[str, int], verification["source_classes"]),
            cast(dict[str, int], verification["feature_codes"]),
        )
        ledger = Ledger(workspace.ledger_path)
        auxiliary = [*inputs.values(), index, *artifacts(workspace)]
        for unit in units:
            outputs = ledger.completed_outputs(
                STAGE, str(unit["unit_id"]), str(unit["inputs_hash"])
            )
            if outputs is None:
                raise ValueError("A completed GeoNames unit no longer verifies")
            auxiliary.extend(p for p in outputs if p.suffix != ".parquet")
        verification["seconds_this_run"] = round(time.monotonic() - started, 3)
        verification["completed_at"] = now()
        report_path = workspace.normalized(SOURCE) / "verification.json"
        write_json(report_path, verification)
        auxiliary.append(report_path)
        write_json(
            workspace.normalized(SOURCE) / "manifest.json",
            {
                "schema_version": "1",
                "source": SOURCE,
                "source_release": inventory["source_release"],
                "units": units,
                "builder_version": BUILDER_VERSION,
                "policy_version": POLICY_VERSION,
                "inputs_hash": digest,
                "inventory": str(workspace.raw(SOURCE) / "inventory.json"),
                "auxiliary": [
                    {"path": str(p), "size": p.stat().st_size, "sha256": sha256_file(p)}
                    for p in auxiliary
                ],
                "verification": verification,
            },
        )
        print(f"GeoNames normalization complete: {verification['counts']}", flush=True)
