"""Collect migration candidates without trusting the presence of files alone."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from pipeline.runtime.jsonio import JSON, Object, digest, sha256_file
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Output

from .inventory import Inventory
from .layout import OFFLOADED
from .mapping import destination
from .paths import legacy_relative


@dataclass
class Candidate:
    stage: str
    unit_id: str
    outputs: dict[str, Output] = field(default_factory=dict)
    inputs: dict[str, str] = field(default_factory=dict)
    countries: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    custody: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.stage, self.unit_id

    def add(self, output: Output) -> None:
        if output.path in self.outputs and self.outputs[output.path] != output:
            raise ValueError(f"Conflicting adoption records for {output.path}")
        self.outputs[output.path] = output


def collect(
    ledger: Ledger,
    inventory: Inventory,
) -> tuple[dict[tuple[str, str], Candidate], list[Object]]:
    candidates: dict[tuple[str, str], Candidate] = {}
    changes: list[Object] = []
    for row in ledger.db.execute("SELECT * FROM units ORDER BY stage,unit_id"):
        outputs = cast(list[Object], json.loads(row["outputs"]))
        stage = str(row["stage"])
        unit_id = legacy_relative(str(row["unit_id"]), inventory.root)
        mapped = destination(inventory, stage, unit_id, outputs)
        change: Object = {
            "old_stage": stage,
            "old_unit": unit_id,
            "stage": mapped.stage,
            "unit": mapped.unit_id,
            "reason": mapped.reason,
        }
        changes.append(change)
        if mapped.stage is None:
            continue
        key = mapped.stage, mapped.unit_id
        candidate = candidates.setdefault(key, Candidate(*key))
        candidate.inputs[f"{stage}/{unit_id}"] = row["inputs_hash"]
        relocations: list[JSON] = []
        for raw in outputs:
            original = inventory.output(raw)
            output = inventory.output(raw, base=stage.startswith("golden."))
            if mapped.stage == "lookups" and stage == "golden.static":
                # Normalization retains these exact bytes under its active tables.
                kind = original.path.split("/")[2]
                active = (
                    f"{inventory.active_prefix}/lookups/{kind}/{Path(output.path).name}"
                )
                output = Output(active, original.size, original.sha256)
            if output.path != original.path:
                relocations.append({"from": original.path, "to": output.path})
            candidate.add(output)
        if relocations:
            change["relocations"] = relocations
        metadata = json.loads(row["metadata"])
        candidate.countries = metadata.get("countries", candidate.countries)
    for source, manifest in inventory.sources.items():
        for stage in ("download", "normalize"):
            if (stage, source) not in candidates:
                raise ValueError(f"Manifest lacks a committed {stage} for {source}")
        normalized = candidates["normalize", source]
        for item in cast(list[Object], manifest["units"]):
            receipt_key = f"{item['stage']}/{item['unit_id']}"
            if normalized.inputs.get(receipt_key) != item["inputs_hash"]:
                raise ValueError(
                    f"Manifest references an uncommitted unit: {receipt_key}"
                )
        for item in cast(list[Object], manifest["partitions"]):
            output = inventory.output(item)
            if normalized.outputs.get(output.path) != output:
                raise ValueError(f"Unmapped normalized partition: {output.path}")
        for output in inventory.source_outputs(source):
            stage = "download" if output.path.startswith("raw/") else "normalize"
            candidates[stage, source].add(output)
        custody = inventory.root / OFFLOADED / f"{source}.json"
        if source in inventory.offloaded:
            candidate = candidates["download", source]
            candidate.custody = f"{OFFLOADED}/{source}.json"
            candidate.add(
                Output(candidate.custody, custody.stat().st_size, sha256_file(custody))
            )
    return candidates, changes


def parameters(candidate: Candidate) -> Object:
    return {"adopted_inputs": digest(candidate.inputs)}
