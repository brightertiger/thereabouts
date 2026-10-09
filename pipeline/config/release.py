"""Versioned release settings; publication remains opt-in until configured."""

import math
import re
from dataclasses import dataclass, field

from h3.api import basic_int as h3
from omegaconf import II

from pipeline.runtime.paths import validate_relative

PACK_FAMILIES = ("core", "postal", "airports", "locode", "phone", "ip", "plates")
MULTIPART_MIN_BYTES = 5 * 1024 * 1024
# Sampled pack checks, each a share of applicable samples that must agree.
ACCEPTANCE_CHECKS = (
    "reverse",
    "ocean",
    "names",
    "alternate_names",
    "postal",
    "airports_iata",
    "airports_icao",
    "locode",
    "ip_v4",
    "ip_v6",
    "phone",
    "plates",
    "vectors",
)


@dataclass
class DatasetLimits:
    max_output_bytes: int = II("resources.max_workspace")
    batch_rows: int = 1024
    row_group_rows: int = 16384
    compression: str = "zstd"
    cell_group_resolution: int = 1


@dataclass
class PackSettings:
    families: list[str] = field(default_factory=lambda: list(PACK_FAMILIES))


@dataclass
class AcceptanceSettings:
    seed: int = 20261010
    # The macOS default soft limit; the reader must work within it.
    open_files: int = 256
    land_cells: int = 10000
    ocean_points: int = 1000
    names: int = 1000
    forward_rows: int = 500
    failures_kept: int = 20
    timeout_seconds: int = 7200
    minimum: dict[str, float] = field(
        default_factory=lambda: dict.fromkeys(ACCEPTANCE_CHECKS, 1.0)
    )


@dataclass
class PublishSettings:
    read_bytes: int = 1_048_576
    multipart_bytes: int = MULTIPART_MIN_BYTES
    # A private staging copy may still carry OWNER DECISION text; a public one not.
    private: bool = False


@dataclass
class ReleaseSettings:
    enabled: bool = False
    version: str = ""
    title: str = "Thereabouts offline geocoding dataset"
    description: str = (
        "Canonical places, H3 reverse lookup and source code observations."
    )
    contact: str = "OWNER DECISION: public maintenance contact"
    citation: str = "OWNER DECISION: preferred dataset citation"
    documentation: str = "OWNER DECISION: public documentation URL"
    update_frequency: str = "Monthly"
    region: str = "OWNER DECISION: release bucket region"
    managed_by: str = "OWNER DECISION: managing organisation"
    adx_categories: list[str] = field(default_factory=lambda: ["Geospatial Data"])
    license: str = "ODbL-1.0"
    previous_version: str = ""
    countries: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    example_latitude: float = 3.139
    example_longitude: float = 101.6869
    schema: str = "config/dataset.yaml"
    readme_template: str = "config/templates/dataset-readme.md"
    dataset: DatasetLimits = field(default_factory=DatasetLimits)
    packs: PackSettings = field(default_factory=PackSettings)
    acceptance: AcceptanceSettings = field(default_factory=AcceptanceSettings)
    publish: PublishSettings = field(default_factory=PublishSettings)


def valid_version(version: str) -> bool:
    return (
        re.fullmatch(r"[0-9]{4}\.(0[1-9]|1[0-2])(?:\.[1-9][0-9]*)?", version)
        is not None
    )


def validate(settings: ReleaseSettings, block_resolution: int) -> None:
    for version in (settings.version, settings.previous_version):
        if version and not valid_version(version):
            raise ValueError("Release versions must use YYYY.MM[.patch]")
    if settings.enabled and not settings.version:
        raise ValueError("An enabled release requires release.version")
    if settings.previous_version and settings.previous_version == settings.version:
        raise ValueError("Previous release must differ from the new version")
    if settings.license != "ODbL-1.0":
        raise ValueError("The derived database release requires ODbL-1.0")
    for path in (settings.schema, settings.readme_template):
        validate_relative(path)
    if any(not re.fullmatch(r"[A-Z]{2}", cc) for cc in settings.countries):
        raise ValueError("Release countries must be uppercase two-letter codes")
    if len(set(settings.countries)) != len(settings.countries):
        raise ValueError("Release countries must be unique")
    for block in settings.blocks:
        try:
            cell = int(block, 16)
        except ValueError as error:
            raise ValueError(f"Invalid release block: {block}") from error
        if not h3.is_valid_cell(cell) or h3.get_resolution(cell) != block_resolution:
            raise ValueError(f"Release block must have resolution {block_resolution}")
    if len(set(settings.blocks)) != len(settings.blocks):
        raise ValueError("Release blocks must be unique")
    limits = settings.dataset
    if any(
        value <= 0
        for value in (limits.max_output_bytes, limits.batch_rows, limits.row_group_rows)
    ):
        raise ValueError("Dataset output and row budgets must be positive")
    if limits.compression not in {"zstd", "snappy"}:
        raise ValueError("Dataset compression must be zstd or snappy")
    if limits.cell_group_resolution != 1:
        # The pack writer reads cells only from group=<r1> partitions.
        raise ValueError("Cell groups must use H3 resolution 1")
    if not set(settings.packs.families) <= set(PACK_FAMILIES) or len(
        set(settings.packs.families)
    ) != len(settings.packs.families):
        raise ValueError("Pack families must be unique supported client families")
    if (
        settings.publish.read_bytes <= 0
        or settings.publish.multipart_bytes < MULTIPART_MIN_BYTES
    ):
        raise ValueError(
            "Publish requires positive reads and at least 5 MiB multipart buffers"
        )
    validate_acceptance(settings.acceptance)
    for value, maximum in (
        (settings.example_latitude, 90),
        (settings.example_longitude, 180),
    ):
        if not math.isfinite(value) or abs(value) > maximum:
            raise ValueError("Release example coordinate is outside WGS84 bounds")


def validate_acceptance(settings: AcceptanceSettings) -> None:
    unknown = set(settings.minimum) - set(ACCEPTANCE_CHECKS)
    if unknown:
        raise ValueError(f"Unknown acceptance check: {sorted(unknown)}")
    if any(not 0 <= value <= 1 for value in settings.minimum.values()):
        raise ValueError("Acceptance minimums must be shares between 0 and 1")
    if settings.open_files < 64:
        raise ValueError("Acceptance needs an open-file limit of at least 64")
    if any(
        value < 0
        for value in (
            settings.land_cells,
            settings.ocean_points,
            settings.names,
            settings.forward_rows,
            settings.failures_kept,
        )
    ):
        raise ValueError("Acceptance sample sizes must be non-negative")
    if settings.timeout_seconds <= 0:
        raise ValueError("Acceptance timeout must be positive")
