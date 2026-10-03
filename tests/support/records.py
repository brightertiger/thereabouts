"""Build-time records; no Python object serialization is used in a pack."""

from dataclasses import dataclass

from shapely.geometry import Polygon


@dataclass
class AdminRecord:
    id: str
    name: str
    code: str
    parent: int
    subdivisions: int
    parts: list[Polygon]
    source_key: str = ""


@dataclass(frozen=True)
class Settlement:
    id: int
    name: str
    feature: str
    lat: float
    lon: float
    country: str
    admin1: str
