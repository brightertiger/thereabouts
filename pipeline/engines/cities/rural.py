"""Repair invalid administrative promotions while retaining the rural distance rule."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, cast

import numpy as np
import shapely
from numpy.typing import NDArray

from pipeline.engines.cells.geometry import Areas, Floats
from pipeline.engines.cells.nearest import nearest
from pipeline.engines.cells.windows import areas, expanded
from pipeline.engines.reconcile.lookup import entity

if TYPE_CHECKING:
    from .engine import Engine


def rural(
    engine: Engine, db: sqlite3.Connection, coordinates: Floats, projected: Floats
) -> tuple[NDArray[np.object_], NDArray[np.object_]]:
    bounds = (
        float(projected[:, 1].min()),
        float(projected[:, 0].min()),
        float(projected[:, 1].max()),
        float(projected[:, 0].max()),
    )
    shapes, records = [], []
    for aid, identity, _, priority, blob, _ in areas(db, expanded(bounds, 0), "city"):
        if aid in engine.rejected:
            continue
        shapes.append(shapely.from_wkb(blob))
        records.append({**entity(db, identity), "cc": "", "priority": priority})
    found = Areas(shapes, records).winners(projected)
    ids = np.array([records[i]["id"] if i >= 0 else None for i in found], dtype=object)
    methods = np.array(
        ["rural_polygon" if i >= 0 else None for i in found], dtype=object
    )
    missing = np.flatnonzero(found < 0)
    index = nearest(engine.source)
    chosen, distances, _ = index.query(coordinates[missing], engine.policy["nearest_m"])
    for row, choice, distance in zip(missing, chosen, distances, strict=True):
        if choice >= 0:
            ids[row] = index.ids[choice]
            methods[row] = (
                "rural_nearest_distant"
                if distance > engine.policy["distant_m"]
                else "rural_nearest"
            )
    return cast(NDArray[np.object_], ids), cast(NDArray[np.object_], methods)
