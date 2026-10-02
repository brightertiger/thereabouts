"""Data-root-relative artifact records for rebuilt golden stages."""

import os
from pathlib import Path
from typing import Any, cast

from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.reconcile.common import Row

PATH_FIELDS = {"path", "base_manifest"}


def relative(path: Path, root: Path) -> str:
    """Keep logical locations, including sibling outputs, without a machine prefix."""
    return Path(os.path.relpath(path.absolute(), root.absolute())).as_posix()


def _convert(value: Any, root: Path, *, resolve: bool, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _convert(v, root, resolve=resolve, key=k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_convert(v, root, resolve=resolve, key=key) for v in value]
    if isinstance(value, str) and key in PATH_FIELDS:
        path = Path(value)
        if resolve:
            return os.path.abspath(root / path)
        return relative(path, root) if path.is_absolute() else value
    return value


def stored(value: Row, root: Path) -> Row:
    """Transform artifact locations only; preserve all other guarded evidence."""
    return cast(Row, _convert(value, root, resolve=False))


def resolved(value: Row, root: Path) -> Row:
    """Resolve relative records; accept historical absolute records."""
    return cast(Row, _convert(value, root, resolve=True))


def digest(value: Row, root: Path) -> str:
    return fingerprint(stored(value, root))


def read(path: Path, root: Path) -> Row:
    return resolved(read_json(path), root)


def write(path: Path, value: Row, root: Path) -> None:
    write_json(path, stored(value, root))


def manifest(path: Path) -> Row:
    """Open a published dataset using its declared relative data-root location."""
    value = read_json(path)
    root = (path.parent / value.get("data_root", ".")).resolve()
    return resolved(value, root)
