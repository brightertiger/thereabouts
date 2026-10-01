"""Bounded, checkpointed gbOpen shapefile conversion and source verification."""

from __future__ import annotations

import gc
import json
import math
import re
import resource
import shutil
import struct
import sys
import time
import unicodedata
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pyarrow as pa
import shapefile
import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, shape
from shapely.geometry.base import BaseGeometry

from . import (
    SCHEMA_HASHES,
    SCHEMAS,
    Ledger,
    Workspace,
    fingerprint,
    sha256_file,
    validate_table,
    write_partition,
)
from .geoboundaries import (
    DOWNLOAD_VERSION,
    SOURCE,
    _archive_path,
    _budget,
    _inventory_path,
    _license_path,
    _object,
    _pin_path,
    _read,
    _unit,
)
from .geoboundaries_json import feature_ids
from .io import write_json

BUILDER_VERSION = "2"
POLICY_VERSION = "retain-all-admin-layers-1"
MAX_GEOMETRY_BYTES = 6_000_000
MAX_SHAPE_BYTES = 120_000_000
BATCH_BYTES = 16_000_000
PARTITION_BYTES = 60_000_000
MAX_ROWS = 2048
KINDS = {"ADM0": "country", "ADM1": "state", "ADM2": "county"}


def _peak_rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss if sys.platform == "darwin" else rss * 1024


def _text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFC", str(value)).split())
    return result if result and result.lower() not in {"none", "null", "nan"} else None


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _polygons(geometry: BaseGeometry) -> Iterator[Polygon]:
    if isinstance(geometry, Polygon):
        if not geometry.is_empty:
            yield geometry
    elif isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for part in geometry.geoms:
            yield from _polygons(part)


def _bounded_geometry(geometry: BaseGeometry, depth: int = 0) -> Iterator[BaseGeometry]:
    """Split only oversized geometries, preserving every positive-area component."""
    if len(geometry.wkb) <= MAX_GEOMETRY_BYTES:
        yield geometry
        return
    if depth >= 32:
        raise ValueError("Geometry could not be divided into bounded rows")
    if isinstance(geometry, MultiPolygon):
        group: list[Polygon] = []
        group_bytes = 9
        for polygon in geometry.geoms:
            size = len(polygon.wkb)
            if group and group_bytes + size > MAX_GEOMETRY_BYTES:
                yield MultiPolygon(group)
                group, group_bytes = [], 9
            if size > MAX_GEOMETRY_BYTES:
                yield from _bounded_geometry(polygon, depth + 1)
            else:
                group.append(polygon)
                group_bytes += size
        if group:
            yield MultiPolygon(group)
        return
    xmin, ymin, xmax, ymax = geometry.bounds
    if xmax - xmin >= ymax - ymin:
        middle = (xmin + xmax) / 2
        windows = (box(xmin, ymin, middle, ymax), box(middle, ymin, xmax, ymax))
    else:
        middle = (ymin + ymax) / 2
        windows = (box(xmin, ymin, xmax, middle), box(xmin, middle, xmax, ymax))
    for window in windows:
        intersection = geometry.intersection(window)
        for polygon in _polygons(intersection):
            yield from _bounded_geometry(polygon, depth + 1)


def _extract(archive_path: Path, directory: Path) -> Path:
    """Extract just the unsimplified shapefile, never duplicate every ZIP member."""
    with zipfile.ZipFile(archive_path) as archive:
        shapes = [
            n
            for n in archive.namelist()
            if n.endswith(".shp") and "_simplified" not in n
        ]
        if len(shapes) != 1:
            raise ValueError("Expected exactly one unsimplified shapefile")
        stem = shapes[0][:-4]
        directory.mkdir(parents=True, exist_ok=True)
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            with (
                archive.open(stem + suffix) as source,
                (directory / ("layer" + suffix)).open("wb") as target,
            ):
                shutil.copyfileobj(source, target, length=1024 * 1024)
    projection = (directory / "layer.prj").read_text(encoding="utf-8")
    if (
        "GEOGCS" not in projection
        or "WGS_1984" not in projection
        or "PROJCS" in projection
    ):
        raise ValueError(f"Unexpected CRS: {projection}")
    return directory / "layer.shp"


def _record_sizes(path: Path) -> Iterator[int]:
    with path.open("rb") as stream:
        header = stream.read(100)
        if len(header) != 100 or struct.unpack_from(">i", header)[0] != 9994:
            raise ValueError("Invalid shapefile header")
        if struct.unpack_from(">i", header, 24)[0] * 2 != path.stat().st_size:
            raise ValueError("Shapefile length mismatch")
        while record := stream.read(8):
            if len(record) != 8:
                raise ValueError("Truncated shapefile record header")
            size = struct.unpack_from(">i", record, 4)[0] * 2
            if size < 4:
                raise ValueError("Invalid shapefile record size")
            yield size
            stream.seek(size, 1)
        if stream.tell() != path.stat().st_size:
            raise ValueError("Truncated shapefile record body")


def _features(
    path: Path,
) -> Iterator[tuple[int, dict[str, Any], BaseGeometry | None, str | None]]:
    """Read one bounded shape; reject before allocating an oversized record."""
    with shapefile.Reader(str(path), encoding="utf-8") as reader:
        fields = [str(field[0]) for field in reader.fields[1:]]
        count = 0
        for index, size in enumerate(_record_sizes(path)):
            count += 1
            record = reader.record(index)
            properties = (
                dict(zip(fields, record, strict=True)) if record is not None else {}
            )
            if size > MAX_SHAPE_BYTES:
                yield (
                    index,
                    properties,
                    None,
                    f"Shape record exceeds {MAX_SHAPE_BYTES} bytes",
                )
                continue
            try:
                source_shape = reader.shape(index)
                if source_shape.shapeType not in (5, 15, 25):
                    raise ValueError(f"Non-polygon shape type {source_shape.shapeType}")
                geometry = shape(source_shape.__geo_interface__)
                if source_shape.shapeType != 5:
                    properties["normalization_dropped_z_or_m"] = True
                del source_shape
                yield index, properties, geometry, None
                del geometry
            except (ValueError, TypeError, shapely.errors.GEOSException) as error:
                yield index, properties, None, f"{type(error).__name__}: {error}"
        if count != reader.numRecords:
            raise ValueError(f"SHP/DBF record mismatch: {count}/{reader.numRecords}")


def _repair(geometry: BaseGeometry) -> tuple[BaseGeometry, list[str]]:
    transformations: list[str] = []
    if geometry.is_empty:
        raise ValueError("Empty source geometry")
    if shapely.get_coordinate_dimension(geometry) != 2:
        geometry = shapely.force_2d(geometry)
        transformations.append("force_2d")
    if not geometry.is_valid:
        geometry = shapely.make_valid(geometry)
        transformations.append("make_valid")
        pieces = list(_polygons(geometry))
        if not pieces:
            raise ValueError("Invalid geometry repairs to no polygonal area")
        if geometry.geom_type == "GeometryCollection":
            transformations.append("non_polygonal_repair_remnants_retained_in_raw")
        geometry = pieces[0] if len(pieces) == 1 else MultiPolygon(pieces)
    if not geometry.is_valid:
        raise ValueError("Repair did not produce valid polygons")
    xmin, ymin, xmax, ymax = geometry.bounds
    if not all(math.isfinite(v) for v in geometry.bounds):
        raise ValueError("Non-finite bounds")
    if xmin < -180 or ymin < -90 or xmax > 180 or ymax > 90:
        if (
            xmin < -180 - 1e-8
            or ymin < -90 - 1e-8
            or xmax > 180 + 1e-8
            or ymax > 90 + 1e-8
        ):
            raise ValueError(f"Geometry outside WGS84 bounds: {geometry.bounds}")
        geometry = geometry.intersection(box(-180, -90, 180, 90))
        transformations.append("clip_sub_1e-8_degree_world_bound_roundoff")
    return geometry, transformations


def _row(
    properties: dict[str, Any],
    geometry: BaseGeometry,
    pin: dict[str, Any],
    country: str | None,
    index: int,
    part: int,
    transformations: list[str],
) -> dict[str, object]:
    metadata = _object(pin["metadata"])
    unit = _unit(metadata)
    identifier = (
        _text(properties.get("shapeID")) or f"{metadata['boundaryID']}:record:{index}"
    )
    level = str(metadata["boundaryType"])
    iso = _text(properties.get("shapeISO"))
    subdivision = (
        iso
        if iso
        and country
        and re.fullmatch(r"[A-Z]{2}-[A-Z0-9]{1,3}", iso)
        and iso.startswith(country + "-")
        else None
    )
    license_url = (
        _text(metadata.get("licenseSource"))
        or "https://www.geoboundaries.org/index.html#citation"
    )
    if not license_url.startswith(("http://", "https://")):
        license_url = "https://" + license_url
    provenance = {
        "source_url": pin["url"],
        "license_url": license_url,
        "attribution": "geoBoundaries; " + str(metadata["boundarySource"]),
        "layer_metadata": metadata,
        "source_properties": properties,
        "commit": pin["commit"],
        "retrieved_at": pin["retrieved_at"],
        "archive_sha256": pin["archive_sha256"],
        "record_index": index,
        "geometry_part": part,
        "transformations": transformations,
        "name_language": None,
        "schema_hash": SCHEMA_HASHES["areas"],
        "country_code_mapping": "GeoNames countryInfo ISO3/ISO2; XK user-assigned",
        "country_reference": {
            "source_url": "https://download.geonames.org/export/dump/countryInfo.txt",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "GeoNames",
        },
        "layer_unit": unit,
        "builder_version": BUILDER_VERSION,
    }
    xmin, ymin, xmax, ymax = geometry.bounds
    return {
        "source": SOURCE,
        "source_id": identifier,
        "entity_id": identifier,
        "kind": KINDS[level],
        "subtype": _text(properties.get("shapeType")) or level,
        "admin_level": level,
        "parent_source_id": None,
        "country_code": country,
        "subdivision_code": subdivision,
        "name": _text(properties.get("shapeName")),
        "name_en": None,
        "geometry": geometry.wkb,
        "xmin": xmin,
        "ymin": ymin,
        "xmax": xmax,
        "ymax": ymax,
        "is_land": None,
        "is_territorial": None,
        "source_release": pin["commit"],
        "license": _text(metadata["boundaryLicense"]) or "Unspecified by source",
        "provenance": _json(provenance),
    }


class _Writer:
    def __init__(self, workspace: Workspace, unit: str, inputs_hash: str) -> None:
        self.workspace = workspace
        self.unit = unit
        self.inputs_hash = inputs_hash
        self.rows: list[dict[str, object]] = []
        self.row_bytes = 0
        self.batches: list[pa.Table] = []
        self.batch_bytes = 0
        self.outputs: list[Path] = []

    def add(self, row: dict[str, object]) -> None:
        size = (
            len(cast(bytes, row["geometry"]))
            + len(str(row["provenance"]).encode("utf-8"))
            + 2048
        )
        if self.rows and (
            self.row_bytes + size > BATCH_BYTES or len(self.rows) >= MAX_ROWS
        ):
            self._batch()
        self.rows.append(row)
        self.row_bytes += size

    def _batch(self) -> None:
        if not self.rows:
            return
        table = pa.Table.from_pylist(self.rows, schema=SCHEMAS["areas"])
        if self.batches and self.batch_bytes + table.nbytes > PARTITION_BYTES:
            self._partition()
        self.batches.append(table)
        self.batch_bytes += table.nbytes
        self.rows, self.row_bytes = [], 0

    def _partition(self) -> None:
        if not self.batches:
            return
        path = self.workspace.partition(
            SOURCE, "areas", self.unit, self.inputs_hash, len(self.outputs)
        )
        _budget(self.workspace, self.batch_bytes * 2)
        write_partition(path, "areas", self.batches)
        self.outputs.append(path)
        self.batches, self.batch_bytes = [], 0

    def finish(self) -> list[Path]:
        self._batch()
        self._partition()
        return self.outputs


def _convert(
    workspace: Workspace,
    pin: dict[str, Any],
    country: str | None,
    inputs_hash: str,
    temporary: Path,
) -> tuple[list[Path], dict[str, Any]]:
    started = time.monotonic()
    metadata = _object(pin["metadata"])
    unit = _unit(metadata)
    archive = _archive_path(workspace, pin)
    shp = _extract(archive, temporary)
    writer = _Writer(workspace, unit, inputs_hash)
    report: dict[str, Any] = {
        "unit_id": unit,
        "input_features": 0,
        "output_rows": 0,
        "accepted_features": 0,
        "invalid_input": 0,
        "repaired_features": 0,
        "split_features": 0,
        "rejects": [],
        "transformations": {},
        "feature_names": [],
        "feature_ids": [],
        "published_feature_count": int(metadata["admUnitCount"]),
        "country_code": country,
    }
    identifiers: set[str] = set()
    for index, properties, geometry, problem in _features(shp):
        report["input_features"] += 1
        identifier = (
            _text(properties.get("shapeID"))
            or f"{metadata['boundaryID']}:record:{index}"
        )
        if identifier in identifiers:
            raise ValueError(f"Duplicate upstream shapeID: {identifier}")
        identifiers.add(identifier)
        if geometry is not None and not geometry.is_valid:
            report["invalid_input"] += 1
        try:
            if geometry is None:
                raise ValueError(problem or "Missing geometry")
            geometry, transformations = _repair(geometry)
            if "make_valid" in transformations:
                report["repaired_features"] += 1
            split = len(geometry.wkb) > MAX_GEOMETRY_BYTES
            if split:
                transformations.append("split_oversized_geometry_preserve_ids")
                report["split_features"] += 1
            feature_rows = [
                _row(properties, piece, pin, country, index, part, transformations)
                for part, piece in enumerate(_bounded_geometry(geometry))
            ]
            if not feature_rows:
                raise ValueError("No polygon rows produced")
            for row in feature_rows:
                validate_table(
                    pa.Table.from_pylist([row], schema=SCHEMAS["areas"]), "areas"
                )
        except (ValueError, shapely.errors.GEOSException) as error:
            report["rejects"].append(
                {
                    "record_index": index,
                    "shape_id": identifier,
                    "properties": properties,
                    "reason": str(error),
                }
            )
            continue
        # Only fully validated features enter the writer. A publication failure
        # fails the unit, never misclassifies partly published rows as a reject.
        for row in feature_rows:
            writer.add(row)
        report["output_rows"] += len(feature_rows)
        report["accepted_features"] += 1
        report["feature_names"].append(_text(properties.get("shapeName")))
        report["feature_ids"].append(identifier)
        for transformation in transformations:
            report["transformations"][transformation] = (
                report["transformations"].get(transformation, 0) + 1
            )
        del geometry, feature_rows
    report["reject_count"] = len(report["rejects"])
    report["publisher_count_matches"] = (
        report["input_features"] == report["published_feature_count"]
    )
    if not report["publisher_count_matches"]:
        report["count_discrepancy"] = _corroborate_count(
            archive, identifiers, int(report["published_feature_count"])
        )
    if report["accepted_features"] + report["reject_count"] != report["input_features"]:
        raise ValueError("Feature accounting mismatch")
    outputs = writer.finish()
    report["parquet_bytes"] = sum(path.stat().st_size for path in outputs)
    report["partitions"] = len(outputs)
    report["elapsed_seconds"] = time.monotonic() - started
    report["schema_geometry_validation"] = "passed for every output row"
    report["peak_rss_bytes"] = _peak_rss_bytes()
    return outputs, report


def _corroborate_count(
    archive_path: Path, identifiers: set[str], published: int
) -> dict[str, object]:
    """Keep source metadata discrepancies when both distributed formats agree."""
    with zipfile.ZipFile(archive_path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".geojson") and "_simplified" not in name
        ]
        if len(names) != 1:
            raise ValueError(
                "Publisher feature count mismatch requires "
                "a bounded independent GeoJSON check"
            )
        with archive.open(names[0]) as stream:
            ids = feature_ids(stream)
        if len(ids) != len(identifiers) or set(ids) != identifiers:
            raise ValueError(
                "Publisher feature count mismatch: SHP and GeoJSON disagree"
            )
        return {
            "published_count": published,
            "actual_count": len(ids),
            "geojson_count": len(ids),
            "geojson_member": names[0],
            "geometry_ids_match": True,
            "explanation": (
                "Publisher metadata disagrees with both distributed SHP "
                "and GeoJSON; every available record retained"
            ),
        }


def _auxiliary(paths: list[Path]) -> list[dict[str, object]]:
    return [
        {
            "path": str(path.resolve()),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def normalize_layers(workspace: Workspace) -> None:
    started = time.monotonic()
    inventory = _read(_inventory_path(workspace))
    ledger = Ledger(workspace.ledger_path)
    units: list[dict[str, str]] = []
    reports: list[dict[str, Any]] = []
    audits: list[Path] = []
    failed: dict[str, str] = {}
    for metadata in inventory["layers"]:
        unit = _unit(metadata)
        temporary = workspace.work / SOURCE / unit
        try:
            pin = _read(_pin_path(workspace, metadata))
            download_hash = fingerprint({"pin": pin, "builder": DOWNLOAD_VERSION})
            if not ledger.is_complete(f"{SOURCE}.download", unit, download_hash):
                raise ValueError("Download unit is not verified complete")
            pin["archive_sha256"] = sha256_file(_archive_path(workspace, pin))
            country = (
                inventory["country_reference"]
                .get(metadata["boundaryISO"], {})
                .get("alpha2")
            )
            inputs_hash = fingerprint(
                {
                    "pin": pin,
                    "builder": BUILDER_VERSION,
                    "policy": POLICY_VERSION,
                    "schema": SCHEMA_HASHES["areas"],
                    "country": country,
                    "max_geometry_bytes": MAX_GEOMETRY_BYTES,
                    "max_shape_bytes": MAX_SHAPE_BYTES,
                }
            )
            audit = (
                workspace.normalized(SOURCE) / "audits" / inputs_hash / f"{unit}.json"
            )
            if not ledger.is_complete(f"{SOURCE}.normalize", unit, inputs_hash):
                with zipfile.ZipFile(_archive_path(workspace, pin)) as archive:
                    expanded = sum(
                        info.file_size
                        for info in archive.infolist()
                        if info.filename.endswith((".shp", ".shx", ".dbf", ".prj"))
                        and "_simplified" not in info.filename
                    )
                _budget(workspace, expanded * 3)
                print(f"NORMALIZE {unit}", flush=True)
                outputs, report = _convert(
                    workspace, pin, country, inputs_hash, temporary
                )
                write_json(audit, report)
                ledger.complete(
                    f"{SOURCE}.normalize",
                    unit,
                    inputs_hash,
                    [*outputs, audit],
                    metadata={
                        key: report[key]
                        for key in (
                            "input_features",
                            "output_rows",
                            "invalid_input",
                            "reject_count",
                            "parquet_bytes",
                            "partitions",
                        )
                    },
                )
                shutil.rmtree(temporary)
            report = _read(audit)
            units.append(
                {
                    "stage": f"{SOURCE}.normalize",
                    "unit_id": unit,
                    "inputs_hash": inputs_hash,
                }
            )
            reports.append(report)
            audits.append(audit)
            print(
                f"NORMALIZED {unit}: {report['input_features']} features, "
                f"{report['output_rows']} rows, {report['reject_count']} rejects",
                flush=True,
            )
        except (
            OSError,
            ValueError,
            zipfile.BadZipFile,
            shapely.errors.GEOSException,
            shapefile.ShapefileException,
        ) as error:
            failed[unit] = f"{type(error).__name__}: {error}"
            print(f"FAILED NORMALIZE {unit}: {error}", flush=True)
        gc.collect()
    summary = _summary(inventory, reports, failed)
    summary["elapsed_seconds"] = time.monotonic() - started
    summary["peak_rss_bytes"] = max(
        _peak_rss_bytes(),
        max((int(report["peak_rss_bytes"]) for report in reports), default=0),
    )
    summary_path = workspace.normalized(SOURCE) / "verification.json"
    write_json(summary_path, summary)
    if failed:
        raise RuntimeError(
            f"{len(failed)} incomplete geoBoundaries units; see {summary_path}"
        )
    for entry in units:
        if (
            ledger.completed_outputs(
                entry["stage"], entry["unit_id"], entry["inputs_hash"]
            )
            is None
        ):
            raise ValueError(
                f"Output verification failed before manifest: {entry['unit_id']}"
            )
    manifest: dict[str, object] = {
        "schema_version": "1",
        "source": SOURCE,
        "source_release": inventory["source_release"],
        "units": units,
        "auxiliary": _auxiliary(
            [
                summary_path,
                _inventory_path(workspace),
                _license_path(workspace),
                *audits,
            ]
        ),
    }
    write_json(workspace.normalized(SOURCE) / "manifest.json", manifest)
    print(
        f"MANIFEST COMPLETE: {len(units)} layers; {summary['output_rows']} rows",
        flush=True,
    )


def _summary(
    inventory: dict[str, Any], reports: list[dict[str, Any]], failed: dict[str, str]
) -> dict[str, Any]:
    by_unit = {str(report["unit_id"]): report for report in reports}
    gbr = by_unit.get("GBR-ADM1")
    usa = by_unit.get("USA-ADM1")
    gbr_names = {"England", "Scotland", "Wales", "Northern Ireland"}
    usa_nonstates = {
        "District of Columbia",
        "Puerto Rico",
        "American Samoa",
        "Guam",
        "United States Virgin Islands",
        "Commonwealth of the Northern Mariana Islands",
    }
    usa_names = set(usa["feature_names"]) if usa else set()
    counts: dict[str, dict[str, int]] = {}
    for level in KINDS:
        selected = [
            report for report in reports if str(report["unit_id"]).endswith(level)
        ]
        counts[level] = {
            "countries": len(selected),
            "features": sum(int(r["input_features"]) for r in selected),
            "rows": sum(int(r["output_rows"]) for r in selected),
        }
    return {
        "source_release": inventory["source_release"],
        "layers": len(reports),
        "by_level": counts,
        "failed": failed,
        "missing_in_api": inventory["missing_in_api"],
        "input_features": sum(int(r["input_features"]) for r in reports),
        "output_rows": sum(int(r["output_rows"]) for r in reports),
        "parquet_bytes": sum(int(r["parquet_bytes"]) for r in reports),
        "partitions": sum(int(r["partitions"]) for r in reports),
        "unit_processing_seconds": sum(
            float(r.get("elapsed_seconds", 0)) for r in reports
        ),
        "invalid_input": sum(int(r["invalid_input"]) for r in reports),
        "repaired_features": sum(int(r["repaired_features"]) for r in reports),
        "split_features": sum(int(r["split_features"]) for r in reports),
        "output_invalid_geometries": 0,
        "inventory_corrections": inventory.get("inventory_corrections", []),
        "coverage_reference": inventory.get("coverage_reference"),
        "publisher_count_discrepancies": {
            r["unit_id"]: r["count_discrepancy"]
            for r in reports
            if "count_discrepancy" in r
        },
        "reject_count": sum(int(r["reject_count"]) for r in reports),
        "spot_checks": {
            "GBR_ADM1": {
                "passed": gbr is not None and set(gbr["feature_names"]) == gbr_names,
                "names": gbr["feature_names"] if gbr else None,
            },
            "USA_ADM1": {
                "passed": usa is not None
                and usa["input_features"] == usa["published_feature_count"]
                and usa["input_features"] == 56
                and len(usa_names) == 56
                and usa_nonstates <= usa_names,
                "count": usa["input_features"] if usa else None,
                "published_count": usa["published_feature_count"] if usa else None,
                "expected_count": 56,
                "state_count": len(usa_names - usa_nonstates),
                "district_and_territory_names": sorted(usa_names & usa_nonstates),
                "expected_composition": "50 states, DC, five inhabited territories",
                "names": usa["feature_names"] if usa else None,
            },
        },
        "dropped_policy_rows": 0,
        "english_names_inferred": 0,
    }
