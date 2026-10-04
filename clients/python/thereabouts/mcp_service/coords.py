"""Strict transport shapes for the shared Rust coordinate parser."""

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidatorFunctionWrapHandler,
    WrapValidator,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Uncertainty(_Strict):
    accuracy_m: StrictFloat | None = None
    hdop: StrictFloat | None = None
    vdop: StrictFloat | None = None


class GeodeticComponents(_Strict):
    lat: StrictFloat
    lon: StrictFloat
    height: StrictFloat | None = None
    height_datum: StrictStr | None = None
    geoid_separation: StrictFloat | None = None


class GeodeticOrigin(GeodeticComponents):
    frame: Literal["geodetic", "latlon", "lla", "llh"] = "geodetic"


class EcefOrigin(_Strict):
    frame: Literal["ecef"]
    x: StrictFloat
    y: StrictFloat
    z: StrictFloat


def _default_geodetic(value: Any, handler: ValidatorFunctionWrapHandler) -> Any:
    # Select the documented default without inventing a declared label in provenance.
    omitted = isinstance(value, dict) and "frame" not in value
    result = handler({**value, "frame": "geodetic"} if omitted else value)
    if omitted:
        result.model_fields_set.discard("frame")
    return result


Origin: TypeAlias = Annotated[
    GeodeticOrigin | EcefOrigin,
    Field(discriminator="frame"),
    WrapValidator(_default_geodetic),
]


class _Point(_Strict):
    uncertainty: Uncertainty | None = None


class GeodeticPoint(GeodeticOrigin, _Point):
    pass


class EcefPoint(EcefOrigin, _Point):
    pass


class EnuPoint(_Point):
    frame: Literal["enu"]
    e: StrictFloat
    n: StrictFloat
    u: StrictFloat
    origin: Origin


class NedPoint(_Point):
    frame: Literal["ned"]
    n: StrictFloat
    e: StrictFloat
    d: StrictFloat
    origin: Origin


class UtmPoint(_Point):
    frame: Literal["utm"]
    zone: StrictInt
    hemisphere: Literal["N", "S"] | None = None
    band: StrictStr | None = None
    easting: StrictFloat
    northing: StrictFloat


class TextPoint(_Point):
    frame: Literal["mgrs", "geohash", "dms", "nmea", "wkt"]
    value: StrictStr


class PluscodePoint(_Point):
    frame: Literal["pluscode"]
    value: StrictStr
    reference: GeodeticComponents | None = None


class CellPoint(_Point):
    frame: Literal["h3", "s2"]
    cell: StrictStr | StrictInt


class GeoJsonPoint(_Point):
    frame: Literal["geojson"]
    coordinates: Annotated[list[StrictFloat], Field(min_length=2, max_length=3)]
    type: Literal["Point"] = "Point"


Point: TypeAlias = Annotated[
    GeodeticPoint
    | EcefPoint
    | EnuPoint
    | NedPoint
    | UtmPoint
    | TextPoint
    | PluscodePoint
    | CellPoint
    | GeoJsonPoint,
    Field(discriminator="frame"),
    WrapValidator(_default_geodetic),
]
