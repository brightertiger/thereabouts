"""Pinned plate documents: the registration pin plus any plate-country pin.

A rule or prior whose document is not pinned is skipped and counted, never
guessed. Every document is checked against its pinned digest before use.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Protocol

import pyarrow.parquet as pq

from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.paths import located

from .policy import Row


class Pins(Protocol):
    def get(self, name: str, /) -> Row | None: ...


class Pool:
    def __init__(self, pins: dict[str, Row]) -> None:
        self.pins = pins
        self.missing: Counter[str] = Counter()
        self.used: dict[str, Row] = {}

    def get(self, name: str, /) -> Row | None:
        pin = self.pins.get(name)
        if pin is None:
            self.missing[name] += 1
            return None
        if name not in self.used:
            if sha256_file(Path(pin["path"])) != pin["sha256"]:
                raise ValueError(f"Corrupt plate evidence: {name}")
            self.used[name] = pin
        return pin


def pool(root: Path, base: Row, extra: list[Row], extra_source: str) -> Pool:
    """Registration documents from its `plate_documents` partition; `extra` holds
    plate-country receipt records of the same files or new ones."""
    parts = [p for p in base["partitions"] if p["kind"] == "plate_documents"]
    if not parts:
        raise ValueError("Missing plate document inventory")
    pins: dict[str, Row] = {}
    for part in parts:
        for item in pq.read_table(located(root, part["path"])).to_pylist():
            pins[item["name"]] = {
                **json.loads(item["metadata"]),
                "url": item["url"],
                "sha256": item["sha256"],
                "path": str(located(root, item["path"])),
                "retrieved_at": item["retrieved_at"],
                "source": base["source"],
            }
    for item in extra:
        pin = {
            **item["upstream"],
            "sha256": item["sha256"],
            "path": str(located(root, item["path"])),
            "source": extra_source,
        }
        known = pins.setdefault(item["name"], pin)
        if known["sha256"] != pin["sha256"]:
            raise ValueError(f"Conflicting plate evidence: {item['name']}")
    return Pool(pins)
