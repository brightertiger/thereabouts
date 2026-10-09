"""Name outputs by role, so a byte-identical file at a new path stales no consumer.

The contract: a unit may name output directories after its own inputs hash, and
every other part of an output path is the same whenever its inputs are. A role is
the path without those directories.
"""

import json
from collections.abc import Container, Iterable, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from .jsonio import JSON, digest, sha256_file
from .paths import relative
from .records import Output


def role(path: str, hashes: Container[str]) -> str:
    """Drop directories named by an inputs hash in `hashes`; the file name stays."""
    *directories, name = path.split("/")
    return "/".join([*(part for part in directories if part not in hashes), name])


@dataclass(frozen=True)
class Hashes:
    """Inputs hashes that may name directories: every recorded one, and the
    unit's own while its outputs are described."""

    recorded: Container[str]
    own: str = ""

    def __contains__(self, name: object) -> bool:
        return name == self.own or name in self.recorded


def _roles(value: JSON, hashes: Container[str]) -> JSON:
    if isinstance(value, str):
        return role(value, hashes)
    if isinstance(value, list):
        return [_roles(item, hashes) for item in value]
    if isinstance(value, dict):
        return {key: _roles(item, hashes) for key, item in value.items()}
    return value


def receipt_digest(payload: bytes, hashes: Container[str]) -> str | None:
    """Digest JSON with the paths it names reduced to roles; None when none moved."""
    try:
        value = json.loads(payload)
        reduced = _roles(value, hashes)
        return digest(reduced) if reduced != value else None
    except ValueError:
        return None


def selected(
    outputs: Iterable[Output], patterns: Sequence[str], inputs_hash: str
) -> list[Output]:
    """Patterns match roles, because exact paths name the producer's inputs hash."""
    return [
        output
        for output in outputs
        if not patterns
        or any(fnmatchcase(role(output.path, (inputs_hash,)), p) for p in patterns)
    ]


def describe(
    root: Path, paths: Sequence[Path], hashes: Container[str] = ()
) -> tuple[tuple[Output, ...], dict[str, str]]:
    outputs, receipts = [], {}
    for path in paths:
        name = relative(root, path)
        if path.name.endswith(".part") or not path.is_file():
            raise ValueError(f"Output has not been published: {name}")
        outputs.append(Output(name, path.stat().st_size, sha256_file(path)))
        if path.suffix == ".json" and (
            value := receipt_digest(path.read_bytes(), hashes)
        ):
            receipts[name] = value
    return tuple(outputs), receipts
