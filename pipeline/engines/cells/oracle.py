"""Vectorized reconciled labels and conservative descendant certificates."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely import STRtree

from pipeline.engines.geo.arrays import FloatArray
from pipeline.engines.geo.sphere import EARTH_M
from pipeline.engines.reconcile.lookup import Locator
from pipeline.engines.store.areas import area_bounds, intersecting_any
from pipeline.engines.store.entities import entity

from .geometry import Areas, boundaries, geometry, inside
from .nearest import nearest
from .offshore import Offshore
from .windows import expanded

Answer = tuple[str | None, str | None, str | None, str | None, str | None]


class Oracle:
    def __init__(
        self,
        locator: Locator,
        paths: dict[str, Path],
        bounds: tuple[float, float, float, float],
    ) -> None:
        self.locator, self.paths, self.bounds = locator, paths, bounds
        self.labelled_points = 0
        self.answers: list[Answer] = [(None, None, None, None, None)]
        self.codes: dict[Answer, int] = {self.answers[0]: 0}
        self.roles = {}
        all_sources: list[bytes] = []
        read_windows = expanded(bounds, locator.policy["offshore_m"])
        expanded_bbox = (
            min(b[0] for b in read_windows),
            min(b[2] for b in read_windows),
            max(b[1] for b in read_windows),
            max(b[3] for b in read_windows),
        )
        land_rows = intersecting_any(locator.land.db, read_windows)
        land_shapes = [geometry(r[4], locator.limits) for r in land_rows]
        self.land_shapes = land_shapes
        self.land_bounds = np.array(
            [area_bounds(locator.land.db, r[0]) for r in land_rows],
            dtype=np.float64,
        ).reshape((-1, 4))
        self.offshore: Offshore | None = None
        self.land = STRtree(land_shapes)
        all_sources.extend(r[4] for r in land_rows)
        for role in ("country", "state", "city"):
            shapes, records = [], []
            for cc, db in locator.countries.items():
                for _, identity, _, priority, wkb, _ in intersecting_any(
                    db, read_windows, role
                ):
                    value = entity(db, identity)
                    records.append({**value, "cc": cc, "priority": priority})
                    shapes.append(geometry(wkb, locator.limits))
                    all_sources.append(wkb)
            self.roles[role] = Areas(shapes, records)
        self.edges = boundaries(all_sources, expanded_bbox, locator.limits)
        self.admin_edges = boundaries(
            all_sources[len(land_shapes) :],
            expanded_bbox,
            locator.limits,
        )

    def intern(self, answer: Answer) -> int:
        if answer not in self.codes:
            self.codes[answer] = len(self.answers)
            self.answers.append(answer)
        return self.codes[answer]

    def labels(
        self, coordinates: FloatArray, *, offshore: bool = True
    ) -> NDArray[np.uint64]:
        self.labelled_points += len(coordinates)
        on_land = inside(self.land, coordinates)
        projected = coordinates.copy()
        eligible = on_land.copy()
        scalar = np.zeros(len(coordinates), dtype=np.bool_)
        if offshore:
            missing = np.flatnonzero(~on_land)
            if len(missing) and self.land_shapes:
                if self.offshore is None:
                    self.offshore = Offshore(
                        self.land_shapes,
                        self.land_bounds,
                        self.locator.limits.offshore_batch_rows,
                    )
                points, present, exceptional = self.offshore.project(
                    coordinates[missing], self.locator.policy["offshore_m"]
                )
                projected[missing], eligible[missing], scalar[missing] = (
                    points,
                    present,
                    exceptional,
                )
        results = np.zeros(len(coordinates), dtype=np.uint64)
        active = np.flatnonzero(eligible)
        points = projected[active]
        country = self.roles["country"].winners(points)
        cc = np.array(
            [
                self.roles["country"].records[c]["cc"] if c >= 0 else None
                for c in country
            ],
            dtype=object,
        )
        state = self.roles["state"].winners(points, cc)
        city = self.roles["city"].winners(points, cc)
        city_ids: list[str | None] = [
            self.roles["city"].records[c]["id"] if c >= 0 else None for c in city
        ]
        methods: list[str | None] = ["area" if c >= 0 else None for c in city]
        for code in sorted({c for c in cc if c is not None}):
            missing = np.flatnonzero((cc == code) & (city < 0))
            if not len(missing):
                continue
            index = nearest(self.paths[code], self.locator.limits)
            chosen, _, _ = index.query(
                coordinates[active[missing]], self.locator.policy["nearest_m"]
            )
            for i, j in zip(missing, chosen, strict=True):
                if j >= 0:
                    city_ids[i], methods[i] = index.ids[j], "nearest"
        for i, out in enumerate(active):
            answer = (
                self.roles["country"].records[country[i]]["id"]
                if country[i] >= 0
                else None,
                self.roles["state"].records[state[i]]["id"] if state[i] >= 0 else None,
                city_ids[i],
                methods[i],
                "land" if on_land[out] else "offshore",
            )
            results[out] = self.intern(answer)
        # Rounding of a spherical projection is observable exactly on a source
        # administrative edge. Reuse the independent oracle in that narrow band.
        offshore_rows = np.flatnonzero(eligible & ~on_land)
        if len(offshore_rows):
            points = shapely.points(
                projected[offshore_rows, 1], projected[offshore_rows, 0]
            )
            scalar[
                offshore_rows[
                    self.admin_edges.query(points, predicate="dwithin", distance=1e-9)[
                        0
                    ]
                ]
            ] = True
        for i in np.flatnonzero(scalar):
            scalar_answer = self.locator.locate(*coordinates[i])
            result: Answer = (
                scalar_answer["country"]["id"] if scalar_answer["country"] else None,
                scalar_answer["state"]["id"] if scalar_answer["state"] else None,
                scalar_answer["city"]["id"] if scalar_answer["city"] else None,
                scalar_answer["city_method"],
                scalar_answer["land_method"],
            )
            results[i] = self.intern(result)
        return results

    def certify(
        self, bounds: FloatArray
    ) -> tuple[NDArray[np.uint64], NDArray[np.bool_]]:
        w, s, e, n = bounds.T
        points = np.column_stack(((s + n) / 2, (w + e) / 2))
        rectangles = shapely.box(w - 1e-11, s - 1e-11, e + 1e-11, n + 1e-11)
        uniform = np.ones(len(bounds), dtype=bool)
        uniform[self.edges.query(rectangles, predicate="intersects")[0]] = False
        on_land = inside(self.land, points)
        # Ocean certificates need empty candidate envelopes for the entire
        # rectangle. Offshore points are always evaluated at finest resolution.
        dy = np.rad2deg(self.locator.policy["offshore_m"] * 1.02 / EARTH_M) + 1e-4
        dx = dy / np.maximum(
            1e-8, np.cos(np.deg2rad(np.minimum(90, np.maximum(abs(s), abs(n)) + dy)))
        )
        expanded = shapely.box(w - dx, s - dy, e + dx, n + dy)
        nearby = np.zeros(len(bounds), dtype=bool)
        nearby[self.land.query(expanded)[0]] = True
        uniform &= on_land | ~nearby
        uniform &= (w > -180 + dx) & (e < 180 - dx) & (s > -90 + dy) & (n < 90 - dy)
        labels = np.zeros(len(bounds), dtype=np.uint64)
        active = np.flatnonzero(uniform & on_land)
        labels[active] = self.labels(points[active], offshore=False)
        radius = np.deg2rad((n - s + e - w) / 2) * EARTH_M + 1e-5
        for cc, path in self.paths.items():
            selected = np.array(
                [
                    i
                    for i in active
                    if self.answers[int(labels[i])][0] == f"country:{cc}"
                    and self.answers[int(labels[i])][3] != "area"
                ],
                dtype=np.int64,
            )
            if not len(selected):
                continue
            _, first, second = nearest(path, self.locator.limits).query(
                points[selected], self.locator.policy["nearest_m"]
            )
            r, cutoff = radius[selected], self.locator.policy["nearest_m"]
            uniform[selected] &= (first - r > cutoff) | (
                (first + r < cutoff) & (second - first > 2 * r + 1e-5)
            )
        return labels, uniform
