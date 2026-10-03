"""Merge structured defaults, YAML, a profile and dot-list overrides."""

import copy
import math
import re
from collections.abc import Sequence
from dataclasses import asdict, fields
from functools import lru_cache
from pathlib import Path
from typing import cast

from omegaconf import OmegaConf
from omegaconf.errors import OmegaConfBaseException

from thereabouts.format import BLOCK_RESOLUTION

from .engine_validation import validate as validate_engines
from .schema import DISK_FLOOR, Config
from .sources import load_sources, resolve_options, validate_source

CONFIG_DIR = Path(__file__).parents[2] / "config"


def load(
    path: Path = CONFIG_DIR / "pipeline.yaml",
    *,
    profile: str | None = None,
    overrides: Sequence[str] = (),
) -> Config:
    files = [
        path,
        *(
            [path.parent / "engines.yaml"]
            if (path.parent / "engines.yaml").exists()
            else []
        ),
        *sorted((path.parent / "sources").glob("*.yaml")),
    ]
    if profile is not None:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", profile):
            raise ValueError("Profile must name a file in config/profiles")
        files.append(path.parent / "profiles" / f"{profile}.yaml")
    stamp = tuple(
        (str(file), file.stat().st_mtime_ns, file.stat().st_size) for file in files
    )
    return copy.deepcopy(_cached(path, profile, tuple(overrides), stamp))


@lru_cache(maxsize=8)
def _cached(
    path: Path,
    profile: str | None,
    overrides: tuple[str, ...],
    stamp: tuple[tuple[str, int, int], ...],
) -> Config:
    return _load(path, profile=profile, overrides=overrides)


def _load(
    path: Path = CONFIG_DIR / "pipeline.yaml",
    *,
    profile: str | None = None,
    overrides: Sequence[str] = (),
) -> Config:
    try:
        tree = OmegaConf.merge(
            OmegaConf.structured(Config),
            {
                "sources": {
                    name: asdict(source)
                    for name, source in load_sources(path.parent / "sources").items()
                }
            },
            {"engines": OmegaConf.load(path.parent / "engines.yaml")}
            if (path.parent / "engines.yaml").exists()
            else {},
            OmegaConf.load(path),
        )
        if profile is not None:
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", profile):
                raise ValueError("Profile must name a file in config/profiles")
            tree = OmegaConf.merge(
                tree, OmegaConf.load(path.parent / "profiles" / f"{profile}.yaml")
            )
        if any("=" not in item for item in overrides):
            raise ValueError("Overrides must have the form section.key=value")
        tree = OmegaConf.merge(tree, OmegaConf.from_dotlist(list(overrides)))
        result = cast(Config, OmegaConf.to_object(tree))
    except OmegaConfBaseException as error:
        raise ValueError(f"Invalid pipeline configuration: {error}") from error
    validate(result)
    return result


def validate(config: Config) -> None:
    for item in fields(config.paths):
        value = getattr(config.paths, item.name)
        if not value:
            raise ValueError(f"paths.{item.name} must not be empty")
        if item.name != "root":
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or path == Path("."):
                raise ValueError(f"paths.{item.name} must be relative to paths.root")
    for name, source in config.sources.items():
        if name != source.name:
            raise ValueError(f"Source key must match its name: {name}")
        validate_source(source)
        resolve_options(source)
    validate_engines(config.engines, config.h3.block_resolution)
    resources = config.resources
    if resources.disk_floor < DISK_FLOOR:
        raise ValueError(f"resources.disk_floor must be at least {DISK_FLOOR}")
    for name in ("workers", "duckdb_threads", "rss_limit", "max_workspace"):
        if getattr(resources, name) <= 0:
            raise ValueError(f"resources.{name} must be positive")
    if (
        not math.isfinite(resources.poll_seconds)
        or not 0 < resources.poll_seconds <= 60
    ):
        raise ValueError("resources.poll_seconds must be in (0, 60]")
    if (
        not math.isfinite(resources.ledger_timeout_seconds)
        or resources.ledger_timeout_seconds < 0
    ):
        raise ValueError(
            "resources.ledger_timeout_seconds must be finite and nonnegative"
        )
    if not re.fullmatch(r"[1-9][0-9]*(MB|GB)", resources.duckdb_memory):
        raise ValueError("resources.duckdb_memory must be a positive MB or GB size")
    if (
        not math.isfinite(resources.workspace_scan_seconds)
        or resources.workspace_scan_seconds <= 0
    ):
        raise ValueError("resources.workspace_scan_seconds must be finite and positive")
    if not 0 <= config.h3.block_resolution <= config.h3.cell_resolution <= 15:
        raise ValueError("h3 resolutions must satisfy 0 <= block <= cell <= 15")
    if config.h3.cell_resolution != 8:
        raise ValueError("h3.cell_resolution must match geographic table semantics (8)")
    if config.h3.block_resolution != BLOCK_RESOLUTION:
        raise ValueError(
            f"h3.block_resolution must match the cell codec ({BLOCK_RESOLUTION})"
        )
    if "local" not in config.storage:
        raise ValueError("storage.local is required")
    for name, url in config.storage.items():
        if not name or "://" not in url:
            raise ValueError(f"storage.{name} must be an fsspec URL")
