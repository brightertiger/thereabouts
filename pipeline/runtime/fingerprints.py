"""The single identity rule: declared code, settings, pins and native versions."""

import importlib.metadata
import sqlite3
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from shapely import geos_version_string

from pipeline.config.schema import Config, StageSettings

from .code import Read, code_hashes
from .jsonio import digest

REPOSITORY = Path(__file__).parents[2]
# Parts of config sections that tune performance only; outputs never read them.
UNHASHED: dict[str, tuple[str, ...]] = {"engines": ("runtime",)}


@lru_cache(maxsize=8)
def locked_versions(payload: bytes) -> dict[str, str]:
    packages = tomllib.loads(payload.decode())["package"]
    return {p["name"]: p["version"] for p in packages}


@lru_cache(maxsize=32)
def installed_version(name: str) -> str:
    # A running process keeps its loaded native libraries; changing uv.lock is
    # still checked on every identity calculation against these versions.
    return importlib.metadata.version(name)


def native_versions(
    names: Sequence[str], lock: Path, read: Read = Path.read_bytes
) -> dict[str, str]:
    pinned = locked_versions(read(lock))
    result = {}
    for name in names:
        if name == "sqlite3":
            # SQLite ships with the interpreter, not a uv.lock distribution.
            result[name] = sqlite3.sqlite_version
            continue
        if name not in pinned:
            raise ValueError(f"No uv.lock pin for native dependency {name}")
        installed = installed_version(name)
        if installed != pinned[name]:
            raise ValueError(f"{name} {installed} differs from uv.lock {pinned[name]}")
        result[name] = installed
    if "shapely" in names:
        result["geos"] = geos_version_string
    return result


def identity(
    packages: Sequence[Path],
    *,
    config: Mapping[str, object],
    pins: Mapping[str, object],
    native: Mapping[str, str],
    cell_format: int | None = None,
    repository: Path = REPOSITORY,
    read: Read = Path.read_bytes,
) -> str:
    return digest(
        {
            "code": code_hashes(packages, repository, read),
            "config": config,
            "pins": pins,
            "native": native,
            "cell_format": cell_format,
        }
    )


def settings_values(config: Config, names: Sequence[str]) -> dict[str, object]:
    tree = asdict(config)
    values: dict[str, object] = {}
    for name in names:
        value = tree[name]
        if isinstance(value, dict):
            value = {
                key: item
                for key, item in value.items()
                if key not in UNHASHED.get(name, ())
            }
        values[name] = value
    return values


def stage_identity(
    settings: StageSettings,
    config: Config,
    *,
    cell_format: int | None = None,
    repository: Path = REPOSITORY,
    read: Read = Path.read_bytes,
) -> str:
    """`cell_format` is the codec version, passed by stages that may declare it."""
    if settings.cell_format and cell_format is None:
        raise ValueError(f"Stage {settings.name} needs the cell format version")
    return identity(
        [repository / path for path in settings.packages],
        config={
            "stage": asdict(settings),
            **settings_values(config, settings.config),
        },
        pins={},
        native=native_versions(settings.native, repository / "uv.lock", read),
        cell_format=cell_format if settings.cell_format else None,
        repository=repository,
        read=read,
    )


def closures(
    config: Config, repository: Path = REPOSITORY
) -> dict[str, dict[str, str]]:
    """Each stage's hashed code, for checking which edits re-identify a stage."""
    return {
        stage.name: code_hashes(
            [repository / path for path in stage.packages], repository
        )
        for stage in config.stages
    }


def adapter_hashes(
    module: str, repository: Path = REPOSITORY, read: Read = Path.read_bytes
) -> dict[str, str]:
    stem = repository.joinpath(*module.split("."))
    path = stem if stem.is_dir() else stem.with_suffix(".py")
    return code_hashes([path], repository, read)
