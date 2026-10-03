"""Measured batch and cache limits inherited from the retained geographic engines."""

from dataclasses import dataclass, field


@dataclass
class EngineLimits:
    city_cache_entries: int = 2
    geometry_cache_entries: int = 24
    large_geometry_bytes: int = 100_000
    edge_segments: int = 64
    nearest_cache_entries: int = 3
    column_cache_entries: int = 96
    reader_cache_entries: int = 24
    offshore_batch_rows: int = 128
    state_vote_batch_rows: int = 1024
    parquet_batch_rows: int = 1024
    source_batch_rows: int = 512
    extract_row_group_rows: int = 2048
    join_row_group_rows: int = 16384
    mapping_batch_rows: int = 2048
    sqlite_cache_kib: int = 16384
    locator_cache_kib: int = 2048
    allocation_batch_rows: int = 1024
    duckdb_spill_bytes: int = 512_000_000
    country_reservation_bytes: int = 256_000_000
    block_reservation_bytes: int = 64_000_000
    lookup_reservation_bytes: int = 512_000_000


@dataclass
class EngineSettings:
    minimum_country_coverage: float = 0.995
    limits: EngineLimits = field(default_factory=EngineLimits)
    reconcile_policy: str = "config/policies/reconcile.yaml"
    city_policies: str = "config/policies/cities"
    city_review: str = "config/reviews/cities-pilot.yaml"
    evaluation_points: str = "eval/city_points/points.csv"
    country_inventory: str = "work/cells/countries.json"
    block_index: str = "work/cells/blocks.sqlite"
    retained_country_inventory: str = "work/golden/countries.json"
    retained_block_index: str = "work/golden/blocks.sqlite"
    reconcile_sources: dict[str, list[str]] = field(default_factory=dict)
    static_sources: dict[str, str] = field(default_factory=dict)
    spatial_sources: dict[str, str] = field(default_factory=dict)
    # Empty selections mean all discovered countries and resolution-3 blocks.
    countries: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
