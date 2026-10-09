"""Name outputs by role, so a byte-identical file at a new path stales no consumer."""

import json
import re
from collections.abc import Iterable, Sequence
from fnmatch import fnmatchcase
from pathlib import Path

from .jsonio import JSON, digest, sha256_file
from .paths import relative
from .records import Output

HASHED = re.compile(r"[0-9a-f]{64}")


def role(path: str) -> str:
    """Drop inputs-hash directories; file names, including content addresses, stay."""
    *directories, name = path.split("/")
    kept = [part for part in directories if not HASHED.fullmatch(part)]
    return "/".join([*kept, name])


def _roles(value: JSON) -> JSON:
    if isinstance(value, str):
        return role(value)
    if isinstance(value, list):
        return [_roles(item) for item in value]
    if isinstance(value, dict):
        return {key: _roles(item) for key, item in value.items()}
    return value


def receipt_digest(payload: bytes) -> str | None:
    """Digest JSON with embedded paths reduced to roles; None when nothing moved."""
    try:
        value = json.loads(payload)
        reduced = _roles(value)
        return digest(reduced) if reduced != value else None
    except ValueError:
        return None


def selected(outputs: Iterable[Output], patterns: Sequence[str]) -> list[Output]:
    """Patterns match roles, because exact paths name the producer's inputs hash."""
    return [
        output
        for output in outputs
        if not patterns or any(fnmatchcase(role(output.path), p) for p in patterns)
    ]


def describe(
    root: Path, paths: Sequence[Path]
) -> tuple[tuple[Output, ...], dict[str, str]]:
    outputs, receipts = [], {}
    for path in paths:
        name = relative(root, path)
        if path.name.endswith(".part") or not path.is_file():
            raise ValueError(f"Output has not been published: {name}")
        outputs.append(Output(name, path.stat().st_size, sha256_file(path)))
        if path.suffix == ".json" and (value := receipt_digest(path.read_bytes())):
            receipts[name] = value
    return tuple(outputs), receipts
