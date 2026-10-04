"""Explicit coordinate inputs and immutable query provenance; maths lives in Rust."""

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal, NotRequired, TypeAlias, TypedDict

import numpy as np

Frame: TypeAlias = Literal[
    "geodetic",
    "latlon",
    "lla",
    "llh",
    "ecef",
    "enu",
    "ned",
    "utm",
    "mgrs",
    "geohash",
    "pluscode",
    "h3",
    "s2",
    "dms",
    "nmea",
    "geojson",
    "wkt",
]


class UncertaintyInput(TypedDict, total=False):
    accuracy_m: float | None
    hdop: float | None
    vdop: float | None


class GeodeticComponents(TypedDict):
    lat: float
    lon: float
    height: NotRequired[float | None]
    height_datum: NotRequired[str | None]
    geoid_separation: NotRequired[float | None]


class GeodeticOrigin(GeodeticComponents):
    frame: NotRequired[Literal["geodetic", "latlon", "lla", "llh"]]


class EcefOrigin(TypedDict):
    frame: Literal["ecef"]
    x: float
    y: float
    z: float


Origin: TypeAlias = GeodeticOrigin | EcefOrigin


class _Input(TypedDict):
    uncertainty: NotRequired[UncertaintyInput | None]


class GeodeticPoint(GeodeticOrigin, _Input):
    pass


class EcefPoint(EcefOrigin, _Input):
    pass


class EnuPoint(_Input):
    frame: Literal["enu"]
    e: float
    n: float
    u: float
    origin: Origin


class NedPoint(_Input):
    frame: Literal["ned"]
    n: float
    e: float
    d: float
    origin: Origin


class UtmPoint(_Input):
    frame: Literal["utm"]
    zone: int
    hemisphere: NotRequired[Literal["N", "S"] | None]
    band: NotRequired[str | None]
    easting: float
    northing: float


class TextPoint(_Input):
    frame: Literal["mgrs", "geohash", "dms", "nmea", "wkt"]
    value: str


class PluscodePoint(_Input):
    frame: Literal["pluscode"]
    value: str
    reference: NotRequired[GeodeticComponents | None]


class CellPoint(_Input):
    frame: Literal["h3", "s2"]
    cell: str | int


class GeoJsonPoint(_Input):
    frame: Literal["geojson"]
    coordinates: list[float] | tuple[float, float] | tuple[float, float, float]
    type: NotRequired[Literal["Point"]]


Point: TypeAlias = (
    GeodeticPoint
    | EcefPoint
    | EnuPoint
    | NedPoint
    | UtmPoint
    | TextPoint
    | PluscodePoint
    | CellPoint
    | GeoJsonPoint
)


@dataclass(frozen=True, slots=True)
class Geodetic:
    lat: float
    lon: float
    height: float | None
    height_datum: str | None
    geoid_separation: float | None


@dataclass(frozen=True, slots=True)
class QueryGeodeticOrigin(Geodetic):
    frame: str


@dataclass(frozen=True, slots=True)
class QueryEcefOrigin:
    frame: str
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class Height:
    value_m: float
    datum: str
    geoid_separation_m: float | None


@dataclass(frozen=True, slots=True)
class Uncertainty:
    accuracy_m: float | None
    hdop: float | None
    vdop: float | None


@dataclass(frozen=True, slots=True)
class BoundaryPoint:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class CellExtent:
    boundary: tuple[BoundaryPoint, ...]
    half_lat_deg: float | None
    half_lon_deg: float | None
    grid_size_m: float | None
    radius_m: float


@dataclass(frozen=True, slots=True)
class NmeaFix:
    talker: str
    sentence: str
    utc: str | None
    quality: int | None
    satellites: int | None


@dataclass(frozen=True, slots=True)
class CoordIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class QueryMetadata:
    input_frame: str
    declared_frame: str | None
    normalized: Geodetic | None
    origin: QueryGeodeticOrigin | QueryEcefOrigin | None
    conversion: tuple[str, ...]
    source_height: Height | None
    uncertainty: Uncertainty
    cell_extent: CellExtent | None
    nmea: NmeaFix | None
    error: CoordIssue | None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QueryMetadata":
        data = value.copy()
        for key, kind in (
            ("normalized", Geodetic),
            ("source_height", Height),
            ("uncertainty", Uncertainty),
            ("nmea", NmeaFix),
            ("error", CoordIssue),
        ):
            if data[key] is not None:
                data[key] = kind(**data[key])
        if data["origin"] is not None:
            origin = data["origin"]
            data["origin"] = (
                QueryEcefOrigin(**origin)
                if origin["frame"] == "ecef"
                else QueryGeodeticOrigin(**origin)
            )
        if data["cell_extent"] is not None:
            extent = data["cell_extent"].copy()
            extent["boundary"] = tuple(BoundaryPoint(**p) for p in extent["boundary"])
            data["cell_extent"] = CellExtent(**extent)
        data["conversion"] = tuple(data["conversion"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["conversion"] = list(self.conversion)
        if self.cell_extent is not None:
            data["cell_extent"]["boundary"] = [
                asdict(p) for p in self.cell_extent.boundary
            ]
        return data


# The same bounded sentinel is used by Node. Null would erase optional numbers.
_INVALID_NUMBER = {"__thereabouts_invalid_number__": True}


def _json_value(value: Any, depth: int = 0) -> Any:
    if depth > 16:
        return _INVALID_NUMBER
    if isinstance(value, (bool, np.bool_)):
        return _INVALID_NUMBER
    if isinstance(value, np.integer):
        value = int(value)
    elif isinstance(value, np.floating):
        value = float(value)
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value if -(1 << 63) <= value < (1 << 64) else _INVALID_NUMBER
    if isinstance(value, float):
        return value if math.isfinite(value) else _INVALID_NUMBER
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Coordinate object keys must be strings")
        return {key: _json_value(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item, depth + 1) for item in value]
    return _INVALID_NUMBER


def _point_json(point: object) -> str:
    if not isinstance(point, Mapping):
        raise TypeError("Use a named coordinate object with an explicit frame")
    return json.dumps(_json_value(point), allow_nan=False, separators=(",", ":"))
