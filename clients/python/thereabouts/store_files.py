"""Strict store-pointer parsing and paths, independent of the legacy pack reader."""

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    """Hash a manifest without interpreting a legacy format."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Duplicate JSON property")
    return value


def _nonfinite(value: str) -> None:
    raise ValueError(f"Nonfinite JSON number: {value}")


def parse(data: str | bytes) -> dict[str, Any]:
    """Admit one object with unique keys and finite JSON numbers."""
    value = json.loads(data, object_pairs_hook=_object, parse_constant=_nonfinite)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def string(value: object) -> str:
    """Require nonempty text for a pointer identity."""
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty string")
    return value


def relative_file(root: Path, name: str) -> Path:
    """Resolve inventoried paths without traversal or symlink escape."""
    root = root.resolve()
    if not name or Path(name).is_absolute() or "\\" in name or ":" in name:
        raise ValueError("Expected a relative artifact path")
    if any(part in ("", ".", "..") for part in name.split("/")):
        raise ValueError("Unsafe artifact path")
    result = root / name
    if not result.resolve().is_relative_to(root):
        raise ValueError("Artifact escapes its data root")
    current = result
    while current != root:
        if current.is_symlink():
            raise ValueError("Symlink artifacts are unsupported")
        current = current.parent
    return result
