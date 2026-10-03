"""Typed normalization options declared by the source adapter modules."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Text:
    pass


@dataclass
class UrbanCentres:
    expected_rows: int = 0


@dataclass
class Names:
    kept_classes: list[str] = field(default_factory=list)
    line_bytes: int = 0
    index_bytes: int = 0
    sqlite_cache_kib: int = 0


@dataclass
class Divisions:
    index_bytes: int = 0
    sqlite_cache_kib: int = 0
    index_batch_rows: int = 0
    point_batch_rows: int = 0
    area_batch_rows: int = 0
    geometry_bytes: int = 0
    geometry_max_depth: int = 0


@dataclass
class Timezones:
    boundary_file: str = ""
    names_file: str = ""
    iana_suffix: str = ""
    cover_batch_rows: int = 0
    geometry_bytes: int = 0
    geometry_max_depth: int = 0
    semantics: str = ""


@dataclass
class Boundaries:
    shape_bytes: int = 0
    geometry_bytes: int = 0
    geometry_max_depth: int = 0
    kinds: dict[str, str] = field(default_factory=dict)


@dataclass
class Land:
    grid_degrees: int = 0
    unit_records: int = 0
    unit_bytes: int = 0
    shape_bytes: int = 0
    index_bytes: int = 0


@dataclass
class Plates:
    pdf_version: str = ""
    example_limit: int = 0
    document_bytes: int = 0
    policy: dict[str, Any] = field(default_factory=dict)
