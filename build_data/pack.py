"""Deterministic NPY/WKB serialization and local pack publication."""

from pathlib import Path
from typing import Any

import numpy as np
import shapely
from numpy.typing import NDArray
from shapely.geometry import Polygon

from .manifest import write_manifest
from .normalize import Audit, BBox
from .records import AdminRecord, Settlement
from .reference.schema import ADMIN_DTYPE, PLACE_DTYPE
from .reference.sphere import unit_vectors


class TextPool:
    def __init__(self) -> None:
        self.values: list[bytes] = []
        self.indices: dict[str, int] = {}
        self.add("")

    def add(self, value: str) -> int:
        if value not in self.indices:
            self.indices[value] = len(self.values)
            self.values.append(value.encode("utf-8"))
        return self.indices[value]


def save(path: Path, name: str, value: NDArray[Any]) -> None:
    np.save(path / f"{name}.npy", value, allow_pickle=False)


def save_blob(
    path: Path, prefix: str, blobs: list[bytes], *, wkb: bool = False
) -> None:
    offsets = np.cumsum([0, *(len(b) for b in blobs)], dtype="<u8")
    save(path, prefix + "_offsets", offsets)
    save(
        path,
        prefix + ("_wkb" if wkb else ""),
        np.frombuffer(b"".join(blobs), dtype="u1"),
    )


def save_geometry(path: Path, layer: str, parts: list[tuple[int, Polygon]]) -> None:
    save_blob(
        path, layer, [shapely.to_wkb(p, byte_order=1) for _, p in parts], wkb=True
    )
    save(path, layer + "_owners", np.array([owner for owner, _ in parts], dtype="<i4"))


def save_admin(path: Path, layer: str, rows: list[AdminRecord], text: TextPool) -> None:
    table = np.array(
        [
            (
                text.add(r.id),
                text.add(r.name),
                text.add(r.code),
                r.parent,
                r.subdivisions,
            )
            for r in rows
        ],
        dtype=ADMIN_DTYPE,
    )
    save(path, "countries" if layer == "country" else layer, table)
    save_geometry(
        path, layer, [(i, part) for i, row in enumerate(rows) for part in row.parts]
    )


def write_pack(
    path: Path,
    countries: list[AdminRecord],
    admin1: list[AdminRecord],
    land: list[Polygon],
    places: list[Settlement],
    bounds: BBox | None,
    audit: Audit,
    *,
    snapshot_id: str,
) -> None:
    path.mkdir(parents=True, exist_ok=False)
    text = TextPool()
    save_admin(path, "country", countries, text)
    save_admin(path, "admin1", admin1, text)
    save_geometry(path, "land", [(0, part) for part in land])
    places = sorted(places, key=lambda p: p.id)
    table = np.array(
        [
            (
                p.id,
                text.add(p.name),
                text.add(p.feature),
                text.add(p.country),
                text.add(p.admin1),
            )
            for p in places
        ],
        dtype=PLACE_DTYPE,
    )
    coordinates = np.array([(p.lat, p.lon) for p in places], dtype="<f8").reshape(-1, 2)
    save(path, "places", table)
    save(path, "coordinates", coordinates)
    save(path, "xyz", unit_vectors(coordinates).astype("<f8"))
    save_blob(path, "text", text.values)
    write_manifest(
        path,
        bounds,
        audit,
        snapshot_id,
        {"countries": len(countries), "admin1": len(admin1), "places": len(places)},
    )
