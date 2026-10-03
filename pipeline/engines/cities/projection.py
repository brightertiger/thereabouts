"""Project onto physical land before applying city footprints offshore."""

from pathlib import Path

import h3
import numpy as np
import shapely
from numpy.typing import NDArray

from pipeline.config.engines import EngineLimits
from pipeline.engines.cells.offshore import Offshore
from pipeline.engines.cells.windows import areas, envelopes, expanded
from pipeline.engines.reconcile.land import Land
from thereabouts.format import BLOCK_RESOLUTION


def project(
    source: tuple[Path, float] | None,
    coordinates: NDArray[np.float64],
    offshore: NDArray[np.bool_],
    limits: EngineLimits,
) -> NDArray[np.float64]:
    result = coordinates.copy()
    groups: dict[str, list[int]] = {}
    for i in np.flatnonzero(offshore):
        y, x = coordinates[i]
        groups.setdefault(h3.latlng_to_cell(y, x, BLOCK_RESOLUTION), []).append(int(i))
    if not groups:
        return result
    if source is None:
        raise ValueError("Offshore city normalization requires verified land input")
    path, cutoff = source
    land = Land(path, limits)
    try:
        for indices in groups.values():
            points = coordinates[indices]
            windows = [w for b in envelopes(points) for w in expanded(b, cutoff)]
            records = areas(land.db, windows)
            shapes = [shapely.from_wkb(r[4]) for r in records]
            bounds = np.array(
                [
                    land.db.execute(
                        "SELECT xmin,xmax,ymin,ymax FROM area_bounds WHERE id=?",
                        (r[0],),
                    ).fetchone()
                    for r in records
                ],
                dtype=np.float64,
            ).reshape((-1, 4))
            projected, present, exceptional = Offshore(
                shapes, bounds, limits.offshore_batch_rows
            ).project(points, cutoff)
            # The scalar path supplies stable ordering for equidistant shorelines.
            for j in np.flatnonzero(exceptional | ~present):
                y, x = points[j]
                found = land.project(x, y, cutoff)
                if found is None:
                    raise ValueError(
                        "Base offshore cell has no matching land projection"
                    )
                projected[j] = found[1], found[0]
            result[indices] = projected
    finally:
        land.close()
    return result
