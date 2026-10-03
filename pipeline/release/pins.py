"""Bind release pin claims to the normalized input inventories actually built."""

from dataclasses import asdict
from pathlib import Path

from pipeline.config import Config
from pipeline.engines.artifacts import read_json
from pipeline.pins.lock import read_lock
from pipeline.pins.models import SourcePin
from pipeline.pins.workspace import from_manifest
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import digest
from pipeline.runtime.paths import located


def selected(config: Config) -> dict[str, SourcePin]:
    pins = read_lock(REPOSITORY / "pins.lock")
    return {
        name: pins[name]
        for name, source in config.sources.items()
        if source.enabled and source.kind != "registration_evidence"
    }


def verify(root: Path, normalized: str, pins: dict[str, SourcePin]) -> None:
    for name, expected in pins.items():
        path = located(root, f"{normalized}/{name}/manifest.json")
        if not path.is_file():
            raise ValueError(
                f"Release pin evidence is missing: {normalized}/{name}/manifest.json"
            )
        actual = from_manifest(root, read_json(path))
        if digest(asdict(actual)) != digest(asdict(expected)):
            raise ValueError(
                f"Release pin differs from built input: {name}; "
                "use the lock matching this snapshot"
            )
