"""Strict metadata parsing and portable checksums."""

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate JSON property")
    return result


def _nonfinite(value: str) -> None:
    raise ValueError(f"Nonfinite JSON number: {value}")


def parse(data: str | bytes) -> dict[str, Any]:
    value = json.loads(data, object_pairs_hook=_object, parse_constant=_nonfinite)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def relative_name(name: str) -> str:
    if not name or Path(name).is_absolute() or "\\" in name or ":" in name:
        raise ValueError("Expected a relative artifact path")
    if any(part in (".", "..", "") for part in name.split("/")):
        raise ValueError("Unsafe artifact path")
    return name


def relative_file(root: Path, name: str) -> Path:
    root = root.resolve()
    relative_name(name)
    result = root / name
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Artifact escapes its data root")
    current = result
    while current != root:
        if current.is_symlink():
            raise ValueError("Symlink artifacts are unsupported")
        current = current.parent
    return result


def integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError("Expected a nonnegative integer")
    return value


def string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected a nonempty string")
    return value


def checksum(value: object) -> str:
    text = string(value)
    if len(text) != 64 or any(c not in "0123456789abcdef" for c in text):
        raise ValueError("Expected a lowercase SHA256")
    return text


def check_file(root: Path, record: dict[str, Any], *, full: bool) -> Path:
    path = relative_file(root, string(record["path"]))
    if not path.is_file() or path.stat().st_size != integer(record["size"]):
        raise ValueError(f"Missing or wrong-sized artifact: {record['path']}")
    expected = checksum(record["sha256"])
    if full and sha256(path) != expected:
        raise ValueError(f"Checksum mismatch: {record['path']}")
    return path
