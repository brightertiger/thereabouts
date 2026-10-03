"""Configuration fields shared by the runner and the stage contracts."""

from dataclasses import dataclass, field

DISK_FLOOR = 5_000_000_000


@dataclass
class Paths:
    root: str = "data"
    raw: str = "raw"
    normalized: str = "normalized"
    reconciled: str = "reconciled"
    cells: str = "cells"
    cities: str = "cities"
    dataset: str = "dataset"
    packs: str = "packs"
    work: str = "work"
    ledger: str = "work/ledger.sqlite3"


@dataclass
class Resources:
    duckdb_memory: str = "1GB"
    duckdb_threads: int = 1
    workers: int = 1
    rss_limit: int = 2_000_000_000
    disk_floor: int = DISK_FLOOR
    max_workspace: int = 60_000_000_000
    poll_seconds: float = 10.0
    ledger_timeout_seconds: float = 30.0
    workspace_scan_seconds: float = 60.0


@dataclass
class H3:
    block_resolution: int = 3
    cell_resolution: int = 8


@dataclass
class StageSettings:
    name: str = ""
    needs: list[str] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    config: list[str] = field(default_factory=list)
    native: list[str] = field(default_factory=list)
    cell_format: bool = False


@dataclass
class Config:
    paths: Paths = field(default_factory=Paths)
    resources: Resources = field(default_factory=Resources)
    h3: H3 = field(default_factory=H3)
    storage: dict[str, str] = field(default_factory=lambda: {"local": "file://"})
    stages: list[StageSettings] = field(default_factory=list)
