"""Shared WGS84 bounds, audited repairs and lossless bounded polygon splitting."""

import math
from collections.abc import Iterator, Sequence
from typing import cast

import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry

WORLD_BOUNDS = (-180.0, -90.0, 180.0, 90.0)
BBOX_COLUMNS = ("xmin", "ymin", "xmax", "ymax")
MULTIPOLYGON_HEADER_BYTES = 9
BOUND_TOLERANCE = 1e-8


class GeometryError(ValueError):
    """Invalid source geometry; distinguish rejects from publication failures."""


def validate_polygon(geometry: BaseGeometry) -> None:
    if (
        geometry.geom_type not in ("Polygon", "MultiPolygon")
        or geometry.is_empty
        or not geometry.is_valid
        or shapely.get_coordinate_dimension(geometry) != 2
    ):
        raise GeometryError("Expected valid nonempty 2D Polygon/MultiPolygon WKB")
    check_bounds(geometry.bounds)


def check_bounds(bounds: Sequence[float]) -> None:
    xmin, ymin, xmax, ymax = bounds
    if not (
        all(math.isfinite(v) for v in bounds)
        and -180 <= xmin <= xmax <= 180
        and -90 <= ymin <= ymax <= 90
    ):
        raise GeometryError(f"Invalid WGS84 bounding box: {tuple(bounds)}")


def bounds_columns(geometry: BaseGeometry) -> dict[str, float]:
    check_bounds(geometry.bounds)
    return dict(zip(BBOX_COLUMNS, geometry.bounds, strict=True))


def polygon_parts(
    geometry: BaseGeometry, *, flatten: bool = False
) -> Iterator[BaseGeometry]:
    if geometry.is_empty:
        return
    if isinstance(geometry, Polygon) or (
        isinstance(geometry, MultiPolygon) and not flatten
    ):
        yield geometry
    elif isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for part in geometry.geoms:
            yield from polygon_parts(part, flatten=flatten)


def repair_geometry(
    geometry: BaseGeometry,
    *,
    collection: str = "reject",
    force_2d: bool = False,
    clip_roundoff: bool = False,
    check_extent: bool = True,
) -> tuple[BaseGeometry, list[str]]:
    """Return the geometry and every transformation; callers count and retain them.

    Collection policy is explicit: OSM rejects nonpolygon remnants, geoBoundaries
    collects polygon components, and Overture audits its retained collection.
    """
    changes: list[str] = []
    if geometry.is_empty:
        raise GeometryError("Empty source geometry")
    if force_2d and shapely.get_coordinate_dimension(geometry) != 2:
        geometry = shapely.force_2d(geometry)
        changes.append("force_2d")
    if not geometry.is_valid:
        geometry = shapely.make_valid(geometry)
        changes.append("make_valid")
        if collection == "collect":
            pieces = list(polygon_parts(geometry, flatten=True))
            if not pieces:
                raise GeometryError("Invalid geometry repairs to no polygonal area")
            if isinstance(geometry, GeometryCollection):
                changes.append("non_polygonal_repair_remnants_retained_in_raw")
            geometry = (
                pieces[0]
                if len(pieces) == 1
                else MultiPolygon(cast(list[Polygon], pieces))
            )
    if (
        geometry.is_empty
        or not geometry.is_valid
        or (
            collection == "reject" and not isinstance(geometry, (Polygon, MultiPolygon))
        )
    ):
        raise GeometryError(
            f"Geometry cannot normalize losslessly: {geometry.geom_type}"
        )
    if clip_roundoff:
        xmin, ymin, xmax, ymax = geometry.bounds
        if all(math.isfinite(v) for v in geometry.bounds) and (
            xmin < -180 or ymin < -90 or xmax > 180 or ymax > 90
        ):
            if (
                xmin < -180 - BOUND_TOLERANCE
                or ymin < -90 - BOUND_TOLERANCE
                or xmax > 180 + BOUND_TOLERANCE
                or ymax > 90 + BOUND_TOLERANCE
            ):
                raise GeometryError(f"Geometry outside WGS84 bounds: {geometry.bounds}")
            geometry = geometry.intersection(box(*WORLD_BOUNDS))
            changes.append("clip_sub_1e-8_degree_world_bound_roundoff")
    if check_extent:
        check_bounds(geometry.bounds)
    return geometry, changes


def split_geometry(
    geometry: BaseGeometry,
    max_bytes: int,
    *,
    max_depth: int = 32,
    flatten_intersections: bool = False,
    depth: int = 0,
) -> Iterator[BaseGeometry]:
    """Split components, then bisect the longest extent; never simplify edges."""
    if len(geometry.wkb) <= max_bytes:
        yield geometry
        return
    if depth >= max_depth:
        raise GeometryError("Geometry could not be divided into bounded rows")

    def split(part: BaseGeometry) -> Iterator[BaseGeometry]:
        return split_geometry(
            part,
            max_bytes,
            max_depth=max_depth,
            flatten_intersections=flatten_intersections,
            depth=depth + 1,
        )

    if isinstance(geometry, MultiPolygon):
        group: list[Polygon] = []
        size = MULTIPOLYGON_HEADER_BYTES
        for polygon in geometry.geoms:
            part_size = len(polygon.wkb)
            if group and size + part_size > max_bytes:
                yield MultiPolygon(group)
                group, size = [], MULTIPOLYGON_HEADER_BYTES
            if part_size > max_bytes:
                yield from split(polygon)
            else:
                group.append(polygon)
                size += part_size
        if group:
            yield MultiPolygon(group)
        return
    xmin, ymin, xmax, ymax = geometry.bounds
    if xmax - xmin >= ymax - ymin:
        middle = (xmin + xmax) / 2
        windows = (box(xmin, ymin, middle, ymax), box(middle, ymin, xmax, ymax))
    else:
        middle = (ymin + ymax) / 2
        windows = (box(xmin, ymin, xmax, middle), box(xmin, middle, xmax, ymax))
    for window in windows:
        for part in polygon_parts(
            geometry.intersection(window), flatten=flatten_intersections
        ):
            yield from split(part)
