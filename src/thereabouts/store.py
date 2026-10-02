"""Persistent pack locations and read-only selection of an active installation."""

import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .errors import DataNotInstalledError
from .packs.errors import CorruptPackError
from .packs.jsonio import parse, relative_file, sha256, string
from .packs.keys import FAMILIES
from .packs.metadata import read_manifest


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
    if family not in FAMILIES:
        raise ValueError("Unsupported pack family")
    # A prefix avoids reserved device names on Windows, including CON and NUL.
    version_directory = "v-" + quote(version, safe="")
    return relative_file(root, f"packs/{family}/{version_directory}/{digest}")


def installed_pack(
    data_dir: str | Path | None = None, *, family: str = "reverse"
) -> Path:
    if family not in FAMILIES:
        raise ValueError("Unsupported pack family")
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
