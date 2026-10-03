"""Reusable offline point oracle over country partitions and the land index."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import shapely

from pipeline.config.engines import EngineLimits

from .classification import city_order
from .common import Row, connect, unpack
from .land import Land
from .spatial import decode, distance, intersecting, windows


def entity(db: sqlite3.Connection, identity: str) -> Row:
    value = db.execute("SELECT data FROM entities WHERE id=?", (identity,)).fetchone()
    if value is None:
        raise ValueError(f"Dangling canonical identity: {identity}")
    result: Row = unpack(value[0])
    return result


def covering(db: sqlite3.Connection, x: float, y: float, role: str) -> list[Row]:
    result: dict[str, Row] = {}
    point = shapely.Point(x, y)
    for _, identity, _, priority, wkb, evidence in intersecting(db, (x, x, y, y), role):
        geometry = decode(wkb)
        if not geometry.covers(point):
            continue
        value = entity(db, identity)
        provenance = unpack(evidence)
        value["boundary_source"] = provenance["source"]
        value["boundary_source_id"] = provenance["source_id"]
        value["area_priority"] = priority
        value["area_degrees2"] = geometry.area
        old = result.get(identity)
        if old is None or priority > old["area_priority"]:
            result[identity] = value
    return list(result.values())


def choose_city(candidates: list[Row]) -> Row | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda e: city_order(e, e["area_priority"], e["area_degrees2"]),
    )


def nearest(
    db: sqlite3.Connection, x: float, y: float, cutoff: float
) -> tuple[Row | None, float | None]:
    # Escalating bounds avoid reading a dense country's entire 50 km circle
    # when the nearest village is metres away. Exact spherical distance decides.
    for radius in sorted({min(cutoff, n) for n in (1000, 5000, 15000, cutoff)}):
        best: tuple[float, str] | None = None
        for left, right, bottom, top in windows(x, y, radius):
            for identity, a, b in db.execute(
                "SELECT p.entity,p.x,p.y FROM point_bounds r "
                "JOIN points p ON p.id=r.id "
                "WHERE r.xmin<=? AND r.xmax>=? AND r.ymin<=? AND r.ymax>=?",
                (right, left, top, bottom),
            ):
                d = distance(x, y, a, b)
                if d <= radius and (best is None or (d, identity) < best):
                    best = d, identity
        if best:
            return entity(db, best[1]), best[0]
    return None, None


class Locator:
    """Open once for many points; close to release bounded SQLite page caches."""

    def __init__(
        self,
        countries: dict[str, Path],
        land: Path,
        policy: Row,
        limits: EngineLimits | None = None,
    ) -> None:
        self.limits = limits or EngineLimits()
        self.countries = {
            cc: connect(path, readonly=True) for cc, path in countries.items()
        }
        self.bounds = {}
        for cc, db in self.countries.items():
            db.execute(f"PRAGMA cache_size=-{self.limits.locator_cache_kib}")
            self.bounds[cc] = db.execute(
                "SELECT xmin,xmax,ymin,ymax FROM area_bounds r "
                "JOIN areas a ON a.id=r.id WHERE a.role='country'"
            ).fetchall()
        self.land = Land(land)
        self.policy = policy

    def close(self) -> None:
        self.land.close()
        for db in self.countries.values():
            db.close()

    def __enter__(self) -> Locator:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def country_candidates(self, x: float, y: float) -> Iterator[tuple[str, Row]]:
        for cc, db in self.countries.items():
            if not any(a <= x <= b and c <= y <= d for a, b, c, d in self.bounds[cc]):
                continue
            for item in covering(db, x, y, "country"):
                yield cc, item

    def locate(self, lat: float, lon: float) -> Row:
        if (
            not math.isfinite(lat)
            or not math.isfinite(lon)
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        ):
            raise ValueError("Coordinates must be finite WGS84 latitude, longitude")
        projection = self.land.project(lon, lat, self.policy["offshore_m"])
        result: Row = {
            "eligible": projection is not None,
            "country": None,
            "state": None,
            "city": None,
            "city_method": None,
            "country_method": None,
            "state_method": None,
            "land_method": None,
            "sovereign": None,
        }
        if projection is None:
            return result
        x, y, method, metres = projection
        result.update(land_method=method, offshore_m=metres, label_point=[y, x])
        countries = list(self.country_candidates(x, y))
        if not countries:
            return result
        countries.sort(
            key=lambda c: (-c[1]["area_priority"], c[1]["area_degrees2"], c[0])
        )
        cc, country = countries[0]
        result["country_conflicts"] = [c for c, _ in countries[1:]]
        db = self.countries[cc]
        states = covering(db, x, y, "state")
        states.sort(key=lambda s: (s["area_degrees2"], s["id"]))
        city = choose_city(covering(db, x, y, "city"))
        city_method, nearest_m = "area" if city else None, None
        if city is None:
            city, nearest_m = nearest(db, lon, lat, self.policy["nearest_m"])
            city_method = "nearest" if city else None
        result.update(
            country=country,
            state=states[0] if states else None,
            city=city,
            city_method=city_method,
            city_distance_m=nearest_m,
            country_method="area",
            state_method="area" if states else None,
            sovereign=country["sovereign"] or [cc, country["name"]],
        )
        return result
