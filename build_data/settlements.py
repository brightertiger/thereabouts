"""GeoNames ingestion and provably complete regional nearest candidates."""

import io
import math
import zipfile
from itertools import pairwise
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from pyofflinegeocoder.schema import EARTH_RADIUS_KM, TIE_TOLERANCE_KM
from pyofflinegeocoder.sphere import unit_vectors

from .normalize import BBox
from .records import Settlement


def read_settlements(path: Path) -> list[Settlement]:
    result: list[Settlement] = []
    with zipfile.ZipFile(path) as archive, archive.open("cities1000.txt") as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8"):
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 19 or fields[6] != "P":
                raise ValueError("Unexpected cities1000 schema or feature class")
            result.append(
                Settlement(
                    int(fields[0]),
                    fields[1],
                    fields[7],
                    float(fields[4]),
                    float(fields[5]),
                    fields[8],
                    fields[10],
                )
            )
    result.sort(key=lambda p: p.id)
    if len({p.id for p in result}) != len(result):
        raise ValueError("Duplicate GeoNames IDs")
    return result


def regional_candidates(
    places: list[Settlement], bounds: BBox | None
) -> list[Settlement]:
    if bounds is None or not places:
        return places
    xyz = unit_vectors(np.array([(p.lat, p.lon) for p in places]))
    tree = cKDTree(xyz)
    w, s, e, n = bounds
    lat_edges = np.linspace(s, n, math.ceil((n - s) / 0.25) + 1)
    lon_edges = np.linspace(w, e, math.ceil((e - w) / 0.25) + 1)
    keep: set[int] = set()
    for south, north in pairwise(lat_edges):
        for west, east in pairwise(lon_edges):
            center = unit_vectors(np.array([(south + north) / 2, (west + east) / 2]))
            chord, _ = tree.query(center)
            nearest = 2 * math.asin(min(1.0, float(chord) / 2))
            # Meridional + equatorial arc lengths bound every point in the cell.
            radius = math.radians((north - south + east - west) / 2)
            limit = min(
                math.pi, nearest + 2 * radius + TIE_TOLERANCE_KM / EARTH_RADIUS_KM
            )
            keep.update(tree.query_ball_point(center, 2 * math.sin(limit / 2) + 2e-15))
    return [places[i] for i in sorted(keep)]
