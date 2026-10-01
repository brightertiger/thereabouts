"""Geoboundaries units."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import shapely

from . import SCHEMAS, Workspace, validate_table
from .geoboundaries_config import SOURCE, _unit
from .geoboundaries_http import _object
from .geoboundaries_pins import _archive_path
from .geoboundaries_reader import _corroborate_count, _extract, _features
from .geoboundaries_rows import _row, _text
from .geoboundaries_settings import (
    BATCH_BYTES,
    MAX_GEOMETRY_BYTES,
    MAX_ROWS,
    PARTITION_BYTES,
)
from .geometry import repair_geometry, split_geometry
from .runtime import peak_rss_bytes
from .writer import PartitionWriter


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
    writer = PartitionWriter(
        workspace,
        SOURCE,
        "areas",
        unit,
        inputs_hash,
        batch_bytes=BATCH_BYTES,
        part_bytes=PARTITION_BYTES,
        batch_rows=MAX_ROWS,
        overhead=2048,
        estimate_fields=("geometry", "provenance"),
    )
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
            geometry, transformations = repair_geometry(
                geometry, collection="collect", force_2d=True, clip_roundoff=True
            )
            if "make_valid" in transformations:
                report["repaired_features"] += 1
            split = len(geometry.wkb) > MAX_GEOMETRY_BYTES
            if split:
                transformations.append("split_oversized_geometry_preserve_ids")
                report["split_features"] += 1
            feature_rows = [
                _row(properties, piece, pin, country, index, part, transformations)
                for part, piece in enumerate(
                    split_geometry(
                        geometry, MAX_GEOMETRY_BYTES, flatten_intersections=True
                    )
                )
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
    report["peak_rss_bytes"] = peak_rss_bytes()
    return outputs, report
