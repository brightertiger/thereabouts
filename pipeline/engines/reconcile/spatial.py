"""Bounded, per-thread prepared geometry and point-in-area tests."""

from __future__ import annotations

import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterator

import shapely
from shapely.geometry.base import BaseGeometry

from pipeline.engines.store.areas import intersecting


class _Decoded(threading.local):
    """Prepared geometries are per thread: GEOS prepares lazily on first use."""

    def __init__(self) -> None:
        self.values: OrderedDict[bytes, BaseGeometry] = OrderedDict()
        self.bytes = 0


_DECODED = _Decoded()


def decode(wkb: bytes) -> BaseGeometry:
    cache = _DECODED
    if wkb in cache.values:
        cache.values.move_to_end(wkb)
        return cache.values[wkb]
    geometry = shapely.from_wkb(wkb)
    while cache.values and cache.bytes + len(wkb) > 32_000_000:
        previous, _ = cache.values.popitem(last=False)
        cache.bytes -= len(previous)
    if len(wkb) <= 32_000_000:
        cache.values[wkb] = geometry
        cache.bytes += len(wkb)
        shapely.prepare(geometry)
    return geometry


def containing(
    db: sqlite3.Connection, x: float, y: float, role: str | None = None
) -> Iterator[tuple[str, str, int, BaseGeometry]]:
    point = shapely.Point(x, y)
    for _, entity, kind, priority, wkb, _ in intersecting(db, (x, x, y, y), role):
        geometry = decode(wkb)
        if geometry.covers(point):
            yield entity, kind, priority, geometry
