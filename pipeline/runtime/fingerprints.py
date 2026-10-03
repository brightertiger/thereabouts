"""The single identity rule: declared code, settings, pins and native versions."""

import importlib.metadata
import tomllib
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

from shapely import geos_version_string

from .code import code_hashes
from .jsonio import digest

REPOSITORY = Path(__file__).parents[2]


@lru_cache(maxsize=8)
def locked_versions(payload: bytes) -> dict[str, str]:
    packages = tomllib.loads(payload.decode())["package"]
    return {p["name"]: p["version"] for p in packages}


@lru_cache(maxsize=32)
def installed_version(name: str) -> str:
    # A running process keeps its loaded native libraries; changing uv.lock is
    # still checked on every identity calculation against these versions.
    return importlib.metadata.version(name)


def native_versions(names: Sequence[str], lock: Path) -> dict[str, str]:
    pinned = locked_versions(lock.read_bytes())
    result = {}
    for name in names:
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
) -> str:
    return digest(
        {
            "code": code_hashes(packages, repository),
            "config": config,
            "pins": pins,
            "native": native,
            "cell_format": cell_format,
        }
    )
