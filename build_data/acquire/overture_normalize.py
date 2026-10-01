"""Bounded Overture conversions, geometry audit and source-unit checkpoints."""

from __future__ import annotations

import hashlib
import json
import math
import os
import resource
import sqlite3
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry, BaseMultipartGeometry

from . import (
    SCHEMA_HASHES,
    SCHEMAS,
    Ledger,
    Workspace,
    fingerprint,
    sha256_file,
    write_partition,
)
from .io import write_json
from .overture import (
    LICENSE_URL,
    PUBLISHED_COUNTS,
    RELEASE_NOTES_URL,
    SOURCE,
    _budget,
    _lock,
)
from .schemas import Kind

BUILDER = "overture-normalize-1"
POLICY = "retain-all-subtypes-no-perspective-selection-1"
GEOMETRY_BYTES = 5_000_000
BATCH_BYTES = 12_000_000
PART_BYTES = 48_000_000
SPOTS = {
    "lower Manhattan": (-74.0060, 40.7128),
    "central Tokyo": (139.6917, 35.6895),
    "Singapore": (103.8198, 1.3521),
    "Pristina": (21.1655, 42.6629),
    "Cayenne": (-52.3333, 4.9333),
}


class RowRejectedError(ValueError):
    """An unusable source feature, distinct from a failed output publication."""


def text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFC", str(value)).split())
    return result or None


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unexpected JSON value: {type(value)}")


def encode(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value or {})


def _labels(row: dict[str, Any]) -> tuple[str | None, str | None]:
    names = _mapping(row.get("names"))
    return text(names.get("primary")), text(_mapping(names.get("common")).get("en"))


def _provenance(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        **context,
        "license_url": LICENSE_URL,
        "attribution": (
            "Overture Maps Foundation; OpenStreetMap contributors; "
            "upstream sources retained below"
        ),
        "upstream": {key: value for key, value in row.items() if key != "geometry"},
        "transformations": [
            "NFC and whitespace display names",
            "all source classifications retained",
        ],
    }


def _common(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "source_id": row["id"],
        "source_release": context["source_release"],
        "license": "ODbL-1.0",
    }


def place(row: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    geometry = shapely.from_wkb(row["geometry"])
    if geometry.is_empty or geometry.geom_type != "Point" or not geometry.is_valid:
        raise RowRejectedError("invalid or non-point division geometry")
    if not (-180 <= geometry.x <= 180 and -90 <= geometry.y <= 90):
        raise RowRejectedError("division coordinates outside WGS84")
    if row.get("population") is not None and row["population"] < 0:
        raise RowRejectedError("negative population")
    name, english = _labels(row)
    if name is None:
        raise RowRejectedError("division lacks required primary name")
    return {
        **_common(row, context),
        "kind": row["subtype"],
        "name": name,
        "name_en": english,
        "latitude": geometry.y,
        "longitude": geometry.x,
        "feature_class": text(row.get("class")),
        "feature_code": None,
        "subtype": row["subtype"],
        "country_code": text(row.get("country")),
        "admin1_code": text(row.get("region")),
        "admin2_code": None,
        "parent_source_id": row.get("parent_division_id"),
        "population": row.get("population"),
        "provenance": encode(_provenance(row, context)),
    }


def names(row: dict[str, Any], context: dict[str, Any]) -> Iterator[dict[str, Any]]:
    source_names = _mapping(row.get("names"))
    candidates: list[dict[str, Any]] = []
    if source_names.get("primary"):
        candidates.append({"value": source_names["primary"], "variant": "primary"})
    candidates.extend(
        {"value": value, "language": language, "variant": "common"}
        for language, value in sorted(_mapping(source_names.get("common")).items())
    )
    candidates.extend(source_names.get("rules") or [])
    for index, rule in enumerate(candidates):
        name = text(rule.get("value"))
        if name is None:
            raise RowRejectedError("empty source alias")
        variant = text(rule.get("variant")) or "rule"
        provenance = {
            **context,
            "license_url": LICENSE_URL,
            "attribution": "Overture Maps Foundation; upstream division sources",
            "upstream_name_rule": rule,
            "source_record_id": row["id"],
            "transformations": ["NFC and whitespace"],
        }
        yield {
            **_common(row, context),
            "source_id": fingerprint(
                {"entity": row["id"], "index": index, "rule": json.loads(encode(rule))}
            ),
            "entity_source_id": row["id"],
            "name": name,
            "language": text(rule.get("language")),
            "name_kind": variant,
            "is_preferred": variant in ("primary", "common"),
            "is_short": variant == "short",
            "is_colloquial": variant == "colloquial",
            "is_historic": variant in ("historic", "historical"),
            "valid_from": text(rule.get("valid_from")),
            "valid_to": text(rule.get("valid_to")),
            "provenance": encode(provenance),
        }


def _polygon_parts(geometry: BaseGeometry) -> Iterator[BaseGeometry]:
    if geometry.is_empty:
        return
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        yield geometry
    elif geometry.geom_type == "GeometryCollection":
        for part in cast(BaseMultipartGeometry, geometry).geoms:
            yield from _polygon_parts(part)


def split_geometry(geometry: BaseGeometry, depth: int = 0) -> Iterator[BaseGeometry]:
    if len(geometry.wkb) <= GEOMETRY_BYTES:
        yield geometry
        return
    if depth >= 24:
        raise RowRejectedError("geometry cannot be split into bounded rows")
    if geometry.geom_type == "MultiPolygon":
        collected: list[Polygon] = []
        size = 9
        for part in cast(BaseMultipartGeometry, geometry).geoms:
            part_size = len(part.wkb)
            if collected and size + part_size > GEOMETRY_BYTES:
                yield MultiPolygon(collected)
                collected, size = [], 9
            if part_size > GEOMETRY_BYTES:
                yield from split_geometry(part, depth + 1)
            else:
                collected.append(cast(Polygon, part))
                size += part_size
        if collected:
            yield MultiPolygon(collected)
        return
    xmin, ymin, xmax, ymax = geometry.bounds
    if xmax - xmin >= ymax - ymin:
        middle = (xmin + xmax) / 2
        tiles = (box(xmin, ymin, middle, ymax), box(middle, ymin, xmax, ymax))
    else:
        middle = (ymin + ymax) / 2
        tiles = (box(xmin, ymin, xmax, middle), box(xmin, middle, xmax, ymax))
    for tile in tiles:
        for part in _polygon_parts(geometry.intersection(tile)):
            yield from split_geometry(part, depth + 1)


def areas(
    row: dict[str, Any],
    context: dict[str, Any],
    parent: str | None,
    stats: Counter[str],
    spots: dict[str, list[dict[str, Any]]],
) -> Iterator[dict[str, Any]]:
    geometry = shapely.from_wkb(row["geometry"])
    provenance = _provenance(row, context)
    if geometry.is_empty:
        stats["empty_input"] += 1
        raise RowRejectedError("empty area geometry")
    if not geometry.is_valid:
        stats["invalid_input"] += 1
        provenance["repair_reason"] = shapely.is_valid_reason(geometry)
        geometry = shapely.make_valid(geometry)
        provenance["transformations"].append("GEOS make_valid")
        stats["repaired_input"] += 1
    else:
        stats["valid_input"] += 1
    if shapely.get_coordinate_dimension(geometry) != 2:
        geometry = shapely.force_2d(geometry)
        provenance["transformations"].append("force_2d")
        stats["forced_2d"] += 1
    name, english = _labels(row)
    oversized = len(geometry.wkb) > GEOMETRY_BYTES
    if geometry.geom_type == "GeometryCollection":
        non_polygon = sum(
            part.geom_type not in ("Polygon", "MultiPolygon", "GeometryCollection")
            for part in cast(BaseMultipartGeometry, geometry).geoms
        )
        stats["repair_non_polygon_components"] += non_polygon
        provenance["repair_non_polygon_components"] = non_polygon
    emitted = 0
    for polygon in _polygon_parts(geometry):
        for part in split_geometry(polygon):
            xmin, ymin, xmax, ymax = part.bounds
            if not all(math.isfinite(v) for v in part.bounds) or not (
                -180 <= xmin <= xmax <= 180 and -90 <= ymin <= ymax <= 90
            ):
                raise RowRejectedError("area bounds outside WGS84")
            part_provenance = {**provenance, "geometry_part": emitted}
            if oversized:
                part_provenance["geometry_split"] = (
                    "components then recursive bbox intersection; no simplification"
                )
            result = {
                **_common(row, context),
                "entity_id": row["division_id"],
                "kind": row["subtype"],
                "subtype": row["subtype"],
                "admin_level": text(row.get("admin_level")),
                "parent_source_id": parent,
                "country_code": text(row.get("country")),
                "subdivision_code": text(row.get("region")),
                "name": name,
                "name_en": english,
                "geometry": part.wkb,
                "xmin": xmin,
                "ymin": ymin,
                "xmax": xmax,
                "ymax": ymax,
                "is_land": row.get("is_land"),
                "is_territorial": row.get("is_territorial"),
                "provenance": encode(part_provenance),
            }
            for label, (x, y) in SPOTS.items():
                if (
                    xmin <= x <= xmax
                    and ymin <= y <= ymax
                    and part.covers(shapely.Point(x, y))
                ):
                    spots[label].append(
                        {
                            key: result[key]
                            for key in (
                                "source_id",
                                "entity_id",
                                "name",
                                "name_en",
                                "subtype",
                                "admin_level",
                                "country_code",
                                "is_land",
                                "is_territorial",
                            )
                        }
                    )
            emitted += 1
            yield result
    if not emitted:
        raise RowRejectedError("area has no polygonal components after repair")
    stats["output_valid_geometries"] += emitted
    stats["additional_split_parts"] += emitted - 1


class Sink:
    """Buffer bounded batches and rotate bounded partitions within one unit."""

    def __init__(
        self, workspace: Workspace, kind: Kind, unit: str, inputs_hash: str
    ) -> None:
        self.workspace, self.kind, self.unit, self.inputs_hash = (
            workspace,
            kind,
            unit,
            inputs_hash,
        )
        self.rows: list[dict[str, Any]] = []
        self.estimate = 0
        self.tables: list[pa.Table] = []
        self.size = 0
        self.paths: list[Path] = []
        self.count = 0

    def add(self, row: dict[str, Any]) -> None:
        size = sum(
            len(v.encode("utf-8"))
            if isinstance(v, str)
            else len(v)
            if isinstance(v, bytes)
            else 16
            for v in row.values()
        )
        if self.rows and (self.estimate + size > BATCH_BYTES or len(self.rows) >= 512):
            self.batch()
        self.rows.append(row)
        self.estimate += size
        self.count += 1

    def batch(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pylist(self.rows, schema=SCHEMAS[self.kind])
        self.rows = []
        self.estimate = 0
        if self.size + table.nbytes > PART_BYTES:
            self.publish()
        self.tables.append(table)
        self.size += table.nbytes

    def publish(self) -> None:
        if not self.tables:
            return
        _budget(self.workspace, self.size)
        path = self.workspace.partition(
            SOURCE, self.kind, self.unit, self.inputs_hash, len(self.paths)
        )
        write_partition(path, self.kind, self.tables)
        self.paths.append(path)
        self.tables = []
        self.size = 0

    def finish(self) -> list[Path]:
        self.batch()
        self.publish()
        return self.paths


def _wait_geometry_turn() -> None:
    if os.environ.get("OVERTURE_SERIAL_GEOMETRY") != "1":
        return
    while True:
        processes = subprocess.run(
            ["ps", "-ax", "-o", "command="], check=True, capture_output=True, text=True
        ).stdout.splitlines()
        busy = [
            line
            for line in processes
            if "-m build_data.acquire " in line
            and "--stage normalize" in line
            and any(f" {source} " in line for source in ("osm_land", "geoboundaries"))
            and "python" in line
            and "uv run" not in line
        ]
        if not busy:
            return
        print("Waiting for other source geometry normalizers to finish", flush=True)
        time.sleep(30)


def _rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def _raw_hash(workspace: Workspace, obj: dict[str, Any]) -> str:
    source = workspace.raw(SOURCE) / obj["relative_path"]
    while not source.exists() and os.environ.get("OVERTURE_WAIT_FOR_DOWNLOAD") == "1":
        print(f"Waiting for raw object: {source.name}", flush=True)
        time.sleep(30)
    checksum = sha256_file(source)
    receipt = json.loads(source.with_name(source.name + ".download.json").read_text())
    if source.stat().st_size != obj["size"] or checksum != receipt["verified_sha256"]:
        raise ValueError(f"Raw object integrity failed: {source}")
    return checksum


def _entity_index(
    workspace: Workspace, inventory: dict[str, Any]
) -> sqlite3.Connection:
    """Small disk-backed identity/parent lookup; no global Python graph."""
    path = workspace.work / SOURCE / "entities.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    objects = [obj for obj in inventory["objects"] if obj["type"] == "division"]
    inputs = {obj["key"]: _raw_hash(workspace, obj) for obj in objects}
    inputs_hash = fingerprint({"raw_inputs": inputs, "builder": "overture-index-1"})
    ledger = Ledger(workspace.ledger_path)
    complete = ledger.is_complete("overture.index", "entities", inputs_hash)
    if not complete:
        # An index is expendable only after its pinned raw inputs are verified.
        path.unlink(missing_ok=True)
        path.with_name(path.name + "-journal").unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA cache_size=-32768")
    db.execute(
        "CREATE TABLE IF NOT EXISTS entities"
        "(id TEXT PRIMARY KEY, parent TEXT) WITHOUT ROWID"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS indexed(unit TEXT PRIMARY KEY, checksum TEXT)"
    )
    for obj in objects:
        source = workspace.raw(SOURCE) / obj["relative_path"]
        checksum = inputs[obj["key"]]
        unit = obj["key"]
        previous = db.execute(
            "SELECT checksum FROM indexed WHERE unit=?", (unit,)
        ).fetchone()
        if previous:
            if previous[0] != checksum:
                raise ValueError("Entity index belongs to different raw bytes")
            continue
        _budget(workspace, 1_000_000_000)
        with db, pq.ParquetFile(source) as parquet:
            for batch in parquet.iter_batches(
                batch_size=4096, columns=["id", "parent_division_id"], use_threads=False
            ):
                db.executemany(
                    "INSERT INTO entities VALUES (?,?)",
                    (
                        (row["id"], row["parent_division_id"])
                        for row in batch.to_pylist()
                    ),
                )
            db.execute("INSERT INTO indexed VALUES (?,?)", (unit, checksum))
    if not complete:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Entity index failed SQLite integrity verification")
        ledger.complete("overture.index", "entities", inputs_hash, [path])
    return db


def _unit(
    workspace: Workspace,
    obj: dict[str, Any],
    parquet: pq.ParquetFile,
    group: int,
    context: dict[str, Any],
    db: sqlite3.Connection,
    ledger: Ledger,
    inputs_hash: str,
) -> tuple[dict[str, str], Path]:
    unit = f"{obj['key']}#row-group={group}"
    record = {
        "stage": "overture.normalize",
        "unit_id": unit,
        "inputs_hash": inputs_hash,
    }
    audit_path = (
        workspace.normalized(SOURCE)
        / "audits"
        / inputs_hash
        / (hashlib.sha256(unit.encode()).hexdigest() + ".json")
    )
    if ledger.is_complete(
        "overture.normalize", unit, inputs_hash
    ) and ledger.is_complete("overture.audit", unit, inputs_hash):
        return record, audit_path
    _budget(
        workspace,
        min(parquet.metadata.row_group(group).total_byte_size * 3, 500_000_000),
    )
    started = time.monotonic()
    kind: Kind = "places" if obj["type"] == "division" else "areas"
    sink = Sink(workspace, kind, unit, inputs_hash)
    aliases = Sink(workspace, "names", unit, inputs_hash)
    stats: Counter[str] = Counter()
    subtypes: Counter[str] = Counter()
    rejects: list[dict[str, Any]] = []
    spots: dict[str, list[dict[str, Any]]] = {name: [] for name in SPOTS}
    for batch in parquet.iter_batches(
        batch_size=128 if kind == "places" else 8, row_groups=[group], use_threads=False
    ):
        if _rss_bytes() > 2_800_000_000:
            raise MemoryError("Overture RSS exceeded 2.8 GB; unit remains unfinished")
        for row in batch.to_pylist():
            stats["input_rows"] += 1
            subtypes[row["subtype"]] += 1
            row_context = {
                **context,
                "row_group": group,
                "row_in_group": stats["input_rows"] - 1,
            }
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
                        "SELECT parent FROM entities WHERE id=?", (row["division_id"],)
                    ).fetchone()
                    if entity is None:
                        stats["missing_division_ids"] += 1
                    for area in areas(
                        row, row_context, entity[0] if entity else None, stats, spots
                    ):
                        sink.add(area)
                stats["accepted_features"] += 1
            except (RowRejectedError, shapely.errors.GEOSException) as error:
                if sink.count != before:
                    raise ValueError(
                        f"Partial feature conversion aborted unit: {row['id']}"
                    ) from error
                rejects.append(
                    {
                        "id": row["id"],
                        "row_in_group": stats["input_rows"] - 1,
                        "reason": str(error),
                    }
                )
                stats["rejected_features"] += 1
    expected = parquet.metadata.row_group(group).num_rows
    if (
        stats["input_rows"] != expected
        or stats["accepted_features"] + stats["rejected_features"] != expected
    ):
        raise ValueError("Row-group source count mismatch")
    outputs = sink.finish() + aliases.finish()
    audit = {
        "unit_id": unit,
        "inputs_hash": inputs_hash,
        "kind": kind,
        "counts": dict(stats),
        "subtypes": dict(subtypes),
        "rejects": rejects,
        "output_rows": {kind: sink.count, "names": aliases.count},
        "spot_checks": spots,
        "elapsed_seconds": time.monotonic() - started,
        "peak_rss_bytes": _rss_bytes(),
    }
    write_json(audit_path, audit)
    ledger.complete("overture.audit", unit, inputs_hash, [audit_path])
    ledger.complete("overture.normalize", unit, inputs_hash, outputs, metadata=audit)
    for output in outputs:
        for temporary in output.parent.glob(f".{output.name}.*.part"):
            temporary.unlink()
    print(
        f"NORMALIZED {obj['type']} group {group}: "
        f"{stats['input_rows']} input, {sink.count} {kind}, {aliases.count} names, "
        f"{len(rejects)} rejects ({time.monotonic() - started:.1f}s)",
        flush=True,
    )
    return record, audit_path


def run(workspace: Workspace) -> None:
    """Require full pinned raw acquisition, then checkpoint each source row group."""
    started = time.monotonic()
    with _lock(workspace, "normalize"):
        inventory = cast(
            dict[str, Any],
            json.loads((workspace.raw(SOURCE) / "inventory.json").read_text()),
        )
        ledger = Ledger(workspace.ledger_path)
        _wait_geometry_turn()
        db = _entity_index(workspace, inventory)
        units: list[dict[str, str]] = []
        audits: list[Path] = []
        try:
            # Exercise polygon conversion early; the complete parent index exists.
            for obj in sorted(
                inventory["objects"], key=lambda item: item["type"] == "division"
            ):
                source = workspace.raw(SOURCE) / obj["relative_path"]
                checksum = _raw_hash(workspace, obj)
                with pq.ParquetFile(source) as parquet:
                    schema_hash = hashlib.sha256(
                        parquet.schema_arrow.serialize().to_pybytes()
                    ).hexdigest()
                    context = {
                        "source_url": obj["url"],
                        "source_release": inventory["source_release"],
                        "raw_sha256": checksum,
                        "etag": obj["etag"],
                        "schema_hash": schema_hash,
                        "retrieved_at": inventory["retrieved_at"],
                        "builder": BUILDER,
                        "policy": POLICY,
                        "entity_inputs": dict(
                            db.execute("SELECT unit, checksum FROM indexed")
                        ),
                    }
                    for group in range(parquet.num_row_groups):
                        if obj["type"] == "division_area":
                            _wait_geometry_turn()
                        inputs_hash = fingerprint(
                            {
                                **context,
                                "row_group": group,
                                "schemas": SCHEMA_HASHES,
                                "geometry_bytes": GEOMETRY_BYTES,
                                "batch_bytes": BATCH_BYTES,
                                "part_bytes": PART_BYTES,
                                "shapely": shapely.__version__,
                                "geos": shapely.geos_version_string,
                                "pyarrow": pa.__version__,
                            }
                        )
                        record, audit = _unit(
                            workspace,
                            obj,
                            parquet,
                            group,
                            context,
                            db,
                            ledger,
                            inputs_hash,
                        )
                        units.append(record)
                        audits.append(audit)
            _finish(workspace, inventory, units, audits, ledger, db, started)
        finally:
            db.close()


def _finish(
    workspace: Workspace,
    inventory: dict[str, Any],
    units: list[dict[str, str]],
    audits: list[Path],
    ledger: Ledger,
    db: sqlite3.Connection,
    started: float,
) -> None:
    totals: Counter[str] = Counter()
    rows: Counter[str] = Counter()
    subtypes: dict[str, Counter[str]] = {"areas": Counter(), "places": Counter()}
    spots: dict[str, list[dict[str, Any]]] = {label: [] for label in SPOTS}
    size = 0
    completed_unit_seconds = 0.0
    peak_rss = _rss_bytes()
    for unit, path in zip(units, audits, strict=True):
        outputs = ledger.completed_outputs(
            unit["stage"], unit["unit_id"], unit["inputs_hash"]
        )
        if outputs is None:
            raise ValueError("Completed normalization output failed final verification")
        size += sum(output.stat().st_size for output in outputs)
        audit = json.loads(path.read_text())
        completed_unit_seconds += audit["elapsed_seconds"]
        peak_rss = max(peak_rss, audit["peak_rss_bytes"])
        totals.update(audit["counts"])
        rows.update(audit["output_rows"])
        subtypes[audit["kind"]].update(audit["subtypes"])
        for label, matches in audit["spot_checks"].items():
            spots[label].extend(matches)
    missing_parents = db.execute(
        "SELECT COUNT(*) FROM entities e LEFT JOIN entities p ON e.parent=p.id "
        "WHERE e.parent IS NOT NULL AND p.id IS NULL"
    ).fetchone()[0]
    summary: dict[str, Any] = {
        "source_release": inventory["source_release"],
        "counts": dict(totals),
        "rows": dict(rows),
        "input_subtypes": {kind: dict(counts) for kind, counts in subtypes.items()},
        "spot_checks": spots,
        "missing_parent_ids": missing_parents,
        "output_bytes": size,
        "elapsed_seconds": time.monotonic() - started,
        "completed_unit_seconds": completed_unit_seconds,
        "peak_rss_bytes": peak_rss,
        "completed_at": datetime.now().astimezone().isoformat(),
    }
    expected: Counter[str] = Counter()
    for obj in inventory["objects"]:
        with pq.ParquetFile(workspace.raw(SOURCE) / obj["relative_path"]) as parquet:
            expected["places" if obj["type"] == "division" else "areas"] += (
                parquet.metadata.num_rows
            )
    actual = {kind: sum(counts.values()) for kind, counts in subtypes.items()}
    if actual != dict(expected):
        raise ValueError("Final source footer count mismatch")
    summary["source_footer_counts"] = dict(expected)
    published = PUBLISHED_COUNTS.get(inventory["source_release"])
    if published is not None and expected != {
        "places": published["division"],
        "areas": published["division_area"],
    }:
        raise ValueError("Source footer counts disagree with published release counts")
    summary["publisher_counts"] = published
    summary["publisher_counts_url"] = RELEASE_NOTES_URL if published else None
    summary["spot_check_roles"] = {
        label: {
            role: sorted(
                {
                    match["name_en"] or match["name"]
                    for match in matches
                    if match["subtype"] in types
                }
            )
            for role, types in {
                "country_or_territory": ("country", "dependency"),
                "state_like": ("region", "macroregion"),
                "locality": ("locality",),
            }.items()
        }
        for label, matches in spots.items()
    }
    path = workspace.normalized(SOURCE) / "verification.json"
    write_json(path, summary)
    audits.append(path)
    write_json(
        workspace.normalized(SOURCE) / "manifest.json",
        {
            "schema_version": "1",
            "source": SOURCE,
            "source_release": inventory["source_release"],
            "units": units,
            "auxiliary": [
                {
                    "path": str(path.resolve()),
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in audits
            ],
            "inventory_sha256": sha256_file(workspace.raw(SOURCE) / "inventory.json"),
            "builder": BUILDER,
            "policy": POLICY,
        },
    )
    print(
        f"NORMALIZATION COMPLETE: {dict(rows)}, "
        f"{totals['rejected_features']} rejects, {size} bytes, "
        f"{time.monotonic() - started:.1f}s",
        flush=True,
    )
