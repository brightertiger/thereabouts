"""Pinned source access, reusing the acquisition client's cache and throttling."""

from pathlib import Path
from typing import Any

from build_data.acquire.io import sha256_file
from build_data.acquire.plates_config import policy as base_policy
from build_data.acquire.plates_http import fetch
from build_data.acquire.plates_reader import document

from .policy import Row, policy


def pins(data: Path, *, offline: bool = True) -> dict[str, Row]:
    result = {}
    for name, source in policy("sources").items():
        if source.get("base"):
            spec = dict(base_policy("sources")[name])
            path = data / "raw" / "plates" / "snapshot" / name
            if not path.exists():
                path = data / "raw" / "plates" / "research" / name
        else:
            spec = dict(source)
            path = data / "raw" / "plates_country" / name
            if not path.exists() and not offline:
                fetch(path.parent, name, spec["download_url"])
        if not path.exists():
            raise FileNotFoundError(f"Missing pinned source {path}; run fetch")
        if sha256_file(path) != spec["sha256"]:
            raise ValueError(f"Source hash differs from pin: {path}")
        result[name] = dict(spec, path=str(path.resolve()))
    return result


def source_fields(pin: Row) -> dict[str, Any]:
    return {
        key: pin.get(key)
        for key in (
            "url",
            "license",
            "license_url",
            "attribution",
            "retrieved_at",
            "sha256",
            "revision",
        )
    }


def text_source(pin: Row) -> str:
    return document(pin).text
