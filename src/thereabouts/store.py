"""Persistent pack locations and read-only selection of an active installation."""

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .errors import DataNotInstalledError
from .packs.errors import CorruptPackError
from .packs.jsonio import parse, relative_file, sha256, string
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


def installation_path(root: Path, version: str, digest: str) -> Path:
    # A prefix avoids reserved device names on Windows, including CON and NUL.
    version_directory = "v-" + quote(version, safe="")
    return relative_file(root, f"packs/reverse/{version_directory}/{digest}")


def installed_pack(data_dir: str | Path | None = None) -> Path:
    root = data_directory(data_dir)
    try:
        pointer = relative_file(root, "packs/reverse/current.json")
        if not pointer.exists():
            raise DataNotInstalledError(
                "No reverse pack installed; run thereabouts data install explicitly"
            )
        value = parse(pointer.read_bytes())
        path = relative_file(root, string(value["path"]))
        if sha256(path / "manifest.json") != value["manifest_sha256"]:
            raise ValueError("Active manifest digest mismatch")
        manifest = read_manifest(path)
        expected = installation_path(
            root, manifest["data_version"], manifest["manifest_sha256"]
        )
        if path != expected:
            raise ValueError("Active path differs from immutable pack identity")
        return path
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CorruptPackError(f"Invalid active pack: {exc}") from exc


def list_packs(data_dir: str | Path | None = None) -> list[dict[str, Any]]:
    root = data_directory(data_dir)
    if not root.exists():
        return []
    try:
        active = installed_pack(root)
    except DataNotInstalledError:
        active = None
    results = []
    for manifest in sorted(root.glob("packs/reverse/v-*/*/manifest.json")):
        path = relative_file(root, manifest.parent.relative_to(root).as_posix())
        value = read_manifest(path)
        results.append(
            {
                "family": value["family"],
                "version": value["data_version"],
                "manifest_sha256": value["manifest_sha256"],
                "path": path.relative_to(root.resolve()).as_posix(),
                "active": path == active,
            }
        )
    return results
