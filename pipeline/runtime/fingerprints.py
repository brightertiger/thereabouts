"""The single identity rule: declared code, settings, pins and native versions."""

import importlib.metadata
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

from shapely import geos_version_string

from .jsonio import digest, sha256_file

REPOSITORY = Path(__file__).parents[2]


def native_versions(names: Sequence[str], lock: Path) -> dict[str, str]:
    packages = tomllib.loads(lock.read_text())["package"]
    pinned = {p["name"]: p["version"] for p in packages}
    result = {}
    for name in names:
        if name not in pinned:
            raise ValueError(f"No uv.lock pin for native dependency {name}")
        installed = importlib.metadata.version(name)
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
    files = {}
    for package in packages:
        if (
            ".." in package.parts
            or not package.is_relative_to(repository / "pipeline")
            or not package.resolve().is_relative_to((repository / "pipeline").resolve())
        ):
            raise ValueError("Stage code must live under pipeline/")
        candidates = [package] if package.is_file() else sorted(package.rglob("*.py"))
        if not candidates:
            raise ValueError(f"Empty stage code package: {package}")
        for path in candidates:
            if path.suffix != ".py":
                raise ValueError(f"Stage code file must be Python: {path}")
            if not path.resolve().is_relative_to((repository / "pipeline").resolve()):
                raise ValueError(f"Stage code symlink escapes pipeline/: {path}")
            files[path.relative_to(repository).as_posix()] = sha256_file(path)
    return digest(
        {
            "code": files,
            "config": config,
            "pins": pins,
            "native": native,
            "cell_format": cell_format,
        }
    )
