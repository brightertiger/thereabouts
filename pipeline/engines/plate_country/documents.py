"""Pinned plate documents: the registration pin plus any plate-country pin.

A rule or prior whose document is not pinned is skipped and counted, never
guessed. Every document is checked against its pinned digest before use.
"""

from collections import Counter
from pathlib import Path
from typing import Protocol

from pipeline.engines.artifacts import read_json
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
    """Registration documents from the inventory its normalized manifest names;
    `extra` holds plate-country receipt records of the same files or new ones."""
    record = base["inventory"]
    path = located(root, record["path"])
    if sha256_file(path) != record["sha256"]:
        raise ValueError(f"Corrupt plate evidence: {record['path']}")
    inventory = read_json(path)
    pins = {
        name: {
            **item["metadata"],
            "url": item["url"],
            "sha256": item["sha256"],
            "path": str(located(root, item["path"])),
            "retrieved_at": inventory["pinned_at"],
            "source": base["source"],
        }
        for name, item in inventory["files"].items()
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
