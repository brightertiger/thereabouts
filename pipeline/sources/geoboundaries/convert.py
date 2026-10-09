"""Retain unsimplified boundaries with repairs and discrepancy evidence."""

import time
from pathlib import Path
from typing import Any

import pyarrow as pa
import shapely

from pipeline.errors import InputIntegrityError
from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.geometry import repair_geometry, split_geometry
from pipeline.sources.shared.rows import RowRejected
from pipeline.sources.shared.schemas import SCHEMAS, validate_table
from pipeline.sources.shared.writer import PartitionWriter

from .reader import _corroborate_count, _features
from .rows import _row, _text


def _convert(
    ctx: SourceContext,
    pin: dict[str, Any],
    country: str | None,
    archive: Path,
    shp: Path,
) -> tuple[list[Path], dict[str, Any]]:
    started = time.monotonic()
    metadata = pin["metadata"]
    options = ctx.settings.options
    unit = f"{metadata['boundaryISO']}-{metadata['boundaryType']}"
    writer = PartitionWriter(ctx, "areas", unit)
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
    for index, properties, geometry, problem in _features(
        shp, int(options["shape_bytes"])
    ):
        report["input_features"] += 1
        identifier = (
            _text(properties.get("shapeID"))
            or f"{metadata['boundaryID']}:record:{index}"
        )
        if identifier in identifiers:
            raise InputIntegrityError(f"Duplicate upstream shapeID: {identifier}")
        identifiers.add(identifier)
        if geometry is not None and not geometry.is_valid:
            report["invalid_input"] += 1
        try:
            if geometry is None:
                raise RowRejected(problem or "Missing geometry")
            geometry, transformations = repair_geometry(
                geometry, collection="collect", force_2d=True, clip_roundoff=True
            )
            if "make_valid" in transformations:
                report["repaired_features"] += 1
            split = len(geometry.wkb) > int(options["geometry_bytes"])
            if split:
                transformations.append("split_oversized_geometry_preserve_ids")
                report["split_features"] += 1
            feature_rows = [
                _row(
                    properties,
                    piece,
                    pin,
                    country,
                    index,
                    part,
                    transformations,
                    options["kinds"],
                )
                for part, piece in enumerate(
                    split_geometry(
                        geometry,
                        int(options["geometry_bytes"]),
                        flatten_intersections=True,
                        max_depth=int(options["geometry_max_depth"]),
                    )
                )
            ]
            if not feature_rows:
                raise RowRejected("No polygon rows produced")
            for row in feature_rows:
                validate_table(
                    pa.Table.from_pylist([row], schema=SCHEMAS["areas"]),
                    "areas",
                    ctx.settings.name,
                    ctx.settings.limits,
                    grid=ctx.grid,
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
            archive,
            identifiers,
            int(report["published_feature_count"]),
            ctx.settings.limits.read_bytes,
            ctx.settings.limits.row_bytes,
        )
    if report["accepted_features"] + report["reject_count"] != report["input_features"]:
        raise ValueError("Feature accounting mismatch")
    outputs = writer.finish()
    report["parquet_bytes"] = sum(path.stat().st_size for path in outputs)
    report["partitions"] = len(outputs)
    ctx.log(f"normalize/{ctx.settings.name} {unit}: {time.monotonic() - started:.3f}s")
    report["schema_geometry_validation"] = "passed for every output row"
    return outputs, report
