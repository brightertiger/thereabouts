"""Frozen GHSL urban centres converted from Mollweide to WGS84 areas."""

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import numpy as np
import shapely
from numpy.typing import NDArray

from pipeline.files import sqlite_readonly

from .contract import SourceContext
from .shared.archives import extract
from .shared.geometry import bounds_columns, repair_geometry
from .shared.lookup_rows import Row
from .shared.manifest import finish
from .shared.rows import canonical_json, provenance
from .shared.writer import PartitionWriter


def inverse_mollweide(xy: NDArray[np.float64]) -> NDArray[np.float64]:
    """Inverse ESRI:54009 (WGS84 semimajor axis), as declared by this package."""
    radius = 6378137.0
    theta = np.arcsin(np.clip(xy[:, 1] / (np.sqrt(2) * radius), -1, 1))
    latitude = np.arcsin(np.clip((2 * theta + np.sin(2 * theta)) / np.pi, -1, 1))
    longitude = np.pi * xy[:, 0] / (2 * np.sqrt(2) * radius * np.cos(theta))
    return cast(NDArray[np.float64], np.rad2deg(np.column_stack((longitude, latitude))))


def records(ctx: SourceContext, path: Path) -> Iterator[Row]:
    db = sqlite_readonly(path)
    try:
        table, column, srs = db.execute(
            "SELECT table_name,column_name,srs_id FROM gpkg_geometry_columns"
        ).fetchone()
        definition = db.execute(
            "SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id=?", (srs,)
        ).fetchone()[0]
        if "Mollweide" not in definition or "6378137" not in definition:
            raise ValueError("Unexpected GHSL CRS")
        # Identifiers come from the pinned, checksum-verified GeoPackage schema.
        query = 'SELECT * FROM "' + table.replace('"', '""') + '"'
        cursor = db.execute(query)
        names = [c[0] for c in cursor.description]
        for values in cursor:
            row = dict(zip(names, values, strict=True))
            blob = row.pop(column)
            envelope = (blob[3] >> 1) & 7
            lengths = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
            if blob[:2] != b"GP" or envelope not in lengths:
                raise ValueError("Invalid GeoPackage geometry header")
            geometry = shapely.from_wkb(blob[8 + lengths[envelope] :])
            geometry = shapely.transform(geometry, inverse_mollweide)
            geometry, changes = repair_geometry(geometry, collection="collect")
            identity = str(row["ID_UC_G0"])
            yield {
                "source": "ghsl",
                "source_id": identity,
                "entity_id": identity,
                "kind": "urban_centre",
                "subtype": "built_up",
                "geometry": geometry.wkb,
                "name": row.get("GC_UCN_MN_2025") or None,
                **bounds_columns(geometry),
                "source_release": ctx.pin.release,
                "license": ctx.settings.licence.id,
                "provenance": canonical_json(
                    provenance(
                        ctx.pin.files[0].url,
                        ctx.settings.licence.url,
                        ctx.settings.licence.attribution,
                        {
                            "upstream": row,
                            "geometry_changes": ["inverse Mollweide", *changes],
                        },
                    )
                ),
            }
    finally:
        db.close()


def normalize(ctx: SourceContext) -> list[Path]:
    if len(ctx.pin.files) != 1:
        raise ValueError("Expected one pinned GHSL archive")
    paths = extract(
        ctx,
        ctx.input(ctx.pin.files[0].name),
        ctx.work / ctx.inputs_hash,
        lambda name: name.endswith(".gpkg"),
    )
    if len(paths) != 1:
        raise ValueError("Expected one GHSL GeoPackage")
    writer = PartitionWriter(ctx, "areas", "world")
    for row in records(ctx, paths[0]):
        writer.add(row)
    expected = int(ctx.settings.options["expected_rows"])
    if writer.count != expected:
        raise ValueError(f"GHSL count differs from pinned {expected} centres")
    return finish(ctx, writer.finish(), paths)
