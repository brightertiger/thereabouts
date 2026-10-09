"""Engine settings: batch sizes shape outputs and are hashed; runtime knobs are not."""

from dataclasses import asdict, dataclass, field


@dataclass
class EngineBatches:
    """Sizes that shape output bytes or processing order; hashed into identities."""

    edge_segments: int = 64
    offshore_batch_rows: int = 128
    state_vote_batch_rows: int = 1024
    parquet_batch_rows: int = 1024
    source_batch_rows: int = 512
    extract_row_group_rows: int = 2048
    join_row_group_rows: int = 16384
    mapping_batch_rows: int = 2048
    allocation_batch_rows: int = 1024


@dataclass
class EngineRuntime:
    """Caches, spill and admission reservations; no output depends on them."""

    city_cache_entries: int = 2
    geometry_cache_entries: int = 24
    large_geometry_bytes: int = 100_000
    nearest_cache_entries: int = 3
    column_cache_entries: int = 96
    reader_cache_entries: int = 24
    sqlite_cache_kib: int = 16384
    locator_cache_kib: int = 2048
    duckdb_spill_bytes: int = 512_000_000
    country_reservation_bytes: int = 256_000_000
    block_reservation_bytes: int = 64_000_000
    lookup_reservation_bytes: int = 512_000_000


@dataclass
class EngineLimits(EngineRuntime, EngineBatches):
    """The merged view engines receive; configure the two sections instead."""


@dataclass
class EngineSettings:
    minimum_country_coverage: float = 0.995
    batches: EngineBatches = field(default_factory=EngineBatches)
    runtime: EngineRuntime = field(default_factory=EngineRuntime)
    reconcile_policy: str = "config/policies/reconcile.yaml"
    city_policies: str = "config/policies/cities"
    city_review: str = "config/reviews/cities-pilot.yaml"
    evaluation_points: str = "eval/city_points/points.csv"
    country_inventory: str = "work/cells/countries.json"
    block_index: str = "work/cells/blocks.sqlite"
    retained_country_inventory: str = "work/golden/countries.json"
    retained_block_index: str = "work/golden/blocks.sqlite"
    land_source: str = ""
    urban_source: str = ""
    registration_source: str = ""
    plate_country_source: str = ""
    reconcile_sources: dict[str, list[str]] = field(default_factory=dict)
    static_sources: dict[str, str] = field(default_factory=dict)
    spatial_sources: dict[str, str] = field(default_factory=dict)
    # Source -> normalized kinds whose rows name canonical cities.
    name_sources: dict[str, list[str]] = field(default_factory=dict)
    # Empty selections mean all discovered countries and resolution-3 blocks.
    countries: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)

    @property
    def limits(self) -> EngineLimits:
        return EngineLimits(**asdict(self.batches), **asdict(self.runtime))
