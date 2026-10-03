"""Persistent pack locations and read-only selection of an active installation."""

import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .errors import DataNotInstalledError
from .store_files import parse, relative_file, sha256, string


def data_directory(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    environment = os.environ.get("THEREABOUTS_DATA")
    if environment:
        return Path(environment).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Thereabouts"
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise DataNotInstalledError("Set THEREABOUTS_DATA or LOCALAPPDATA")
        return Path(base) / "Thereabouts"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local/share") / "thereabouts"


def installation_path(
    root: Path, version: str, digest: str, family: str = "reverse"
) -> Path:
    from .packs.keys import FAMILIES

    if family not in FAMILIES:
        raise ValueError("Unsupported pack family")
    # A prefix avoids reserved device names on Windows, including CON and NUL.
    version_directory = "v-" + quote(version, safe="")
    return relative_file(root, f"packs/{family}/{version_directory}/{digest}")


def installed_pack(
    data_dir: str | Path | None = None, *, family: str = "reverse"
) -> Path:
    from .packs.keys import FAMILIES

    if family not in FAMILIES:
        raise ValueError("Unsupported pack family")
    from .packs.errors import CorruptPackError
    from .packs.metadata import read_manifest

    root = data_directory(data_dir)
    try:
        pointer = relative_file(root, f"packs/{family}/current.json")
        if not pointer.exists():
            raise DataNotInstalledError(
                f"No {family} pack installed; run thereabouts data install explicitly"
            )
        value = parse(pointer.read_bytes())
        path = relative_file(root, string(value["path"]))
        if sha256(path / "manifest.json") != value["manifest_sha256"]:
            raise ValueError("Active manifest digest mismatch")
        manifest = read_manifest(path)
        expected = installation_path(
            root, manifest["data_version"], manifest["manifest_sha256"], family
        )
        if path != expected or manifest["family"] != family:
            raise ValueError("Active path differs from immutable pack identity")
        return path
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CorruptPackError(f"Invalid active pack: {exc}") from exc


def list_packs(data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    from .packs.keys import FAMILIES
    from .packs.metadata import read_manifest

    root = data_directory(data_dir)
    if not root.exists():
        return []
    active = set()
    for family in FAMILIES:
        with suppress(DataNotInstalledError):
            active.add(installed_pack(root, family=family))
    results = []
    for manifest in sorted(root.glob("packs/*/v-*/*/manifest.json")):
        path = relative_file(root, manifest.parent.relative_to(root).as_posix())
        value = read_manifest(path)
        results.append(
            {
                "family": value["family"],
                "version": value["data_version"],
                "manifest_sha256": value["manifest_sha256"],
                "path": path.relative_to(root.resolve()).as_posix(),
                "active": path in active,
            }
        )
    return results


def core_pack(data_dir: str | Path | None = None) -> Path:
    """Discover core data using the existing immutable installation layout."""
    from . import _core, errors

    try:
        root = data_directory(data_dir)
    except DataNotInstalledError as exc:
        raise DataNotInstalledError("thereabouts data install core") from exc
    try:
        pointer = relative_file(root, "packs/core/current.json")
        if not pointer.exists():
            # The old pointer is sufficient to diagnose incompatibility; do not load v1.
            legacy = relative_file(root, "packs/reverse/current.json")
            if legacy.exists():
                raise errors.IncompatibleDataError(
                    "Legacy reverse data requires a format-2 core pack"
                )
            raise DataNotInstalledError("thereabouts data install core")
        value = parse(pointer.read_bytes())
        path = relative_file(root, string(value["path"]))
        digest = sha256(path / "manifest.json")
        if digest != value["manifest_sha256"]:
            raise ValueError("Active manifest digest mismatch")
        info = _core.pack_info(str(path))
        expected = relative_file(
            root, f"packs/core/v-{quote(info['data_version'], safe='')}/{digest}"
        )
        if path != expected:
            raise ValueError("Active path differs from immutable pack identity")
        return path
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise errors.CorruptPackError(f"Invalid active pack: {exc}") from exc
