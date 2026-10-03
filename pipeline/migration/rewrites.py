"""Prepare JSON path changes and update only references to the exact old bytes."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from pipeline.runtime.jsonio import JSON, digest
from pipeline.runtime.records import Output

from .candidates import Candidate
from .inventory import Inventory
from .json_patch import patch
from .layout import NORMALIZED, OFFLOADED, PILOT
from .paths import portable


@dataclass
class Rewrites:
    root: Path
    aliases: dict[str, str] = field(default_factory=dict)
    before: dict[str, bytes] = field(default_factory=dict)
    after: dict[str, bytes] = field(default_factory=dict)
    visiting: set[str] = field(default_factory=set)
    done: set[str] = field(default_factory=set)
    statistics: dict[str, dict[str, int]] = field(default_factory=dict)

    def output(self, record: Output) -> Output:
        if record.path not in self.after:
            return record
        data = self.after[record.path]
        return Output(record.path, len(data), hashlib.sha256(data).hexdigest())

    def rewrite(self, name: str) -> None:
        if name in self.done:
            return
        if name in self.visiting:
            raise ValueError(f"Circular JSON artifact references: {name}")
        self.visiting.add(name)
        original = cast(JSON, json.loads(self.before[name]))
        converted = self.references(portable(original, self.root, self.aliases))
        if name.startswith(OFFLOADED + "/") and isinstance(converted, dict):
            source = str(converted["source"])
            manifest = f"{NORMALIZED}/{source}/manifest.json"
            if manifest in self.before:
                self.rewrite(manifest)
                converted["manifest_sha256"] = digest(
                    json.loads(self.after.get(manifest, self.before[manifest]))
                )
        if converted != original:
            self.after[name], self.statistics[name] = patch(
                self.before[name], original, converted
            )
        self.visiting.remove(name)
        self.done.add(name)

    def references(self, value: JSON) -> JSON:
        if isinstance(value, list):
            return [self.references(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: self.references(item) for key, item in value.items()}
        name = result.get("path")
        if isinstance(name, str) and name in self.before and "sha256" in result:
            self.rewrite(name)
            original = self.before[name]
            # A historical review must not become an approval of different evidence.
            if result["sha256"] == hashlib.sha256(original).hexdigest() and result.get(
                "size"
            ) == len(original):
                current = self.after.get(name, original)
                result.update(
                    size=len(current), sha256=hashlib.sha256(current).hexdigest()
                )
        return result


def prepare(
    inventory: Inventory,
    candidates: dict[tuple[str, str], Candidate],
) -> Rewrites:
    names = set()
    for candidate in candidates.values():
        for output in candidate.outputs.values():
            if output.path.endswith(".json") and not (
                output.path.startswith("raw/")
                and not output.path.endswith(("inventory.json", ".download.json"))
            ):
                names.add(output.path)
    names.update(
        p.relative_to(inventory.root).as_posix()
        for p in (inventory.root / PILOT).glob("*gate.json")
    )
    result = Rewrites(inventory.root, aliases=inventory.aliases)
    for name in sorted(names):
        path = inventory.root / name
        if path.is_file():
            result.before[name] = path.read_bytes()
    for name in result.before:
        result.rewrite(name)
    # Retain only changed originals; a full unchanged checkpoint tree is expendable.
    result.before = {name: result.before[name] for name in result.after}
    result.after.update(inventory.imports)
    return result
