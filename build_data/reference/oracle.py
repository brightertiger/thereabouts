"""Original-point polygon and spherical-nearest labels; never shipped in the wheel."""

from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import cKDTree

from pyofflinegeocoder.format import CITY_CUTOFF_KM, pack_label, unpack_label
from pyofflinegeocoder.models import Location

from .administration import Administration
from .pack import Pack
from .schema import EARTH_RADIUS_KM, TIE_TOLERANCE_KM
from .sphere import distances, unit_vectors

FloatArray = NDArray[np.float64]
Labels = NDArray[np.uint64]
DISTANCE_ROUNDING_KM = 1e-10
CHORD_ROUNDING = 2e-15
CERTIFICATE_MARGIN_KM = 1e-8


class Reference:
    """One deterministic policy for scalar oracle, batch builder and benchmarks.

    Ambiguous polygons choose the lexically smallest source ID independently
    for country and state. Settlement ties choose the lowest GeoNames ID.
    """

    def __init__(self, path: Path) -> None:
        self.pack = Pack(path)
        self.pack.verify()
        self.admin = Administration(self.pack)
        self.countries = [
            (self.pack.text(int(r["name"])), self.pack.text(int(r["code"])) or None)
            for r in self.pack.arrays["countries"]
        ]
        self.states = [
            self.pack.text(int(r["name"])) for r in self.pack.arrays["admin1"]
        ]
        names = [self.pack.text(int(r["name"])) for r in self.pack.arrays["places"]]
        self.cities = [None, *sorted(set(names))]
        names_to_id = {name: i for i, name in enumerate(self.cities)}
        self.city_ids = np.array([names_to_id[n] for n in names], dtype=np.uint64)
        self.xyz = np.asarray(self.pack.arrays["xyz"])
        self.tree = cKDTree(self.xyz) if len(self.xyz) else None
        self.labelled_points = 0

    def nearest(self, coordinates: FloatArray) -> tuple[Labels, FloatArray, FloatArray]:
        if self.tree is None:
            return (
                np.zeros(len(coordinates), dtype=np.uint64),
                np.full(len(coordinates), np.inf),
                np.full(len(coordinates), np.inf),
            )
        xyz = unit_vectors(coordinates)
        chords, rows = self.tree.query(xyz, k=2)
        # Stable atan2 distances, with the original complete tie-radius search.
        indices = rows[:, 0].copy()
        selected_xyz = self.xyz[indices]
        km = (
            np.arctan2(
                np.linalg.norm(np.cross(xyz, selected_xyz), axis=1),
                np.sum(xyz * selected_xyz, axis=1),
            )
            * EARTH_RADIUS_KM
        )
        second = np.where(
            np.isfinite(chords[:, 1]),
            2 * np.arcsin(np.minimum(1, chords[:, 1] / 2)) * EARTH_RADIUS_KM,
            np.inf,
        )
        ties = np.flatnonzero(second - km <= TIE_TOLERANCE_KM + DISTANCE_ROUNDING_KM)
        for i in ties:
            indices[i], km[i] = self._tied_nearest(xyz[i], float(chords[i, 0]))
        cities = np.where(km <= CITY_CUTOFF_KM, self.city_ids[indices], 0).astype(
            np.uint64
        )
        return cities, km, second

    def _tied_nearest(self, query: FloatArray, chord: float) -> tuple[int, float]:
        """Search the complete tie radius; source rows ascend by GeoNames ID."""
        assert self.tree is not None
        radius = min(2.0, chord + TIE_TOLERANCE_KM / EARTH_RADIUS_KM + CHORD_ROUNDING)
        candidates = np.asarray(
            self.tree.query_ball_point(query, np.nextafter(radius, np.inf)),
            dtype=np.int64,
        )
        km = distances(query, self.xyz[candidates])
        selected = int(candidates[km <= km.min() + TIE_TOLERANCE_KM].min())
        return selected, float(distances(query, self.xyz[[selected]])[0])

    def labels(self, coordinates: FloatArray) -> Labels:
        self.labelled_points += len(coordinates)
        country, state, present = self.admin.membership(coordinates)
        city = np.zeros(len(coordinates), dtype=np.uint64)
        city[present] = self.nearest(coordinates[present])[0]
        return pack_label(country, state, city, present)

    def certify(self, bounds: FloatArray) -> tuple[Labels, NDArray[np.bool_]]:
        """Prove constancy on a rectangle containing EVERY descendant centre."""
        w, s, e, n = bounds.T
        coordinates = np.column_stack(((s + n) / 2, (w + e) / 2))
        country, state, present = self.admin.membership(coordinates)
        admin_ok = self.admin.uniform(bounds)
        city, nearest, second = self.nearest(coordinates)
        # A meridian then parallel route is at most this equatorial arc length.
        radius = (
            np.deg2rad((n - s + e - w) / 2) * EARTH_RADIUS_KM + CERTIFICATE_MARGIN_KM
        )
        city_ok = (nearest - radius > CITY_CUTOFF_KM) | (
            (nearest + radius < CITY_CUTOFF_KM)
            & (
                second - nearest
                > 2 * radius + 2 * TIE_TOLERANCE_KM + CERTIFICATE_MARGIN_KM
            )
        )
        uniform = admin_ok & (~present | city_ok)
        return pack_label(country, state, city, present), uniform

    def scalar(self, lat: float, lon: float) -> Location | None:
        """Independent scalar polygon predicates and exhaustive tie handling."""
        bounds = self.pack.manifest["coverage_bbox"]
        if bounds is not None:
            w, s, e, n = bounds
            if not (w <= lon <= e and s <= lat <= n):
                return None
        rows = {
            layer: index.query(lat, lon) for layer, index in self.admin.layers.items()
        }
        if not rows["country"] and not rows["land"]:
            return None
        c = min(
            rows["country"], key=lambda i: self.admin.ranks["country"][i], default=-1
        )
        srow = min(
            rows["admin1"], key=lambda i: self.admin.ranks["admin1"][i], default=-1
        )
        city: str | None = None
        if self.tree is not None:
            query = unit_vectors(np.array([lat, lon]))
            chord, _ = self.tree.query(query)
            selected, distance = self._tied_nearest(query, float(chord))
            if distance <= CITY_CUTOFF_KM:
                city = self.cities[int(self.city_ids[selected])]
        country, code = self.countries[c] if c >= 0 else (None, None)
        return Location(city, self.states[srow] if srow >= 0 else None, country, code)

    def locations(self, labels: Labels) -> list[Location | None]:
        return [self.location(int(label)) for label in labels]

    def location(self, label: int) -> Location | None:
        if label == 0:
            return None
        c, state, city = unpack_label(label)
        country, code = self.countries[c] if c >= 0 else (None, None)
        return Location(
            self.cities[city], self.states[state] if state >= 0 else None, country, code
        )

    def catalog(self) -> dict[str, Any]:
        return {
            "countries": self.countries,
            "states": self.states,
            "cities": self.cities,
        }

    def close(self) -> None:
        self.admin.close()
        self.tree = None
        self.xyz = np.empty((0, 3))
        self.pack.close()
