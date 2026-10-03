"""Adopt manifest-only tables and already-recorded evaluation evidence."""

from pathlib import Path
from typing import cast

from pipeline.runtime.jsonio import Object, read_object, sha256_file
from pipeline.runtime.records import Output

from .candidates import Candidate
from .inventory import Inventory
from .layout import PILOT


def file_output(root: Path, name: str) -> Output:
    path = root / name
    return Output(name, path.stat().st_size, sha256_file(path))


def add_evidence(
    inventory: Inventory,
    candidates: dict[tuple[str, str], Candidate],
) -> None:
    if inventory.base_pointer:
        candidate = candidates["cells", "snapshot/current"]
        candidate.add(file_output(inventory.root, "base_cells/current.json"))
        for table in cast(list[Object], inventory.base["tables"]):
            candidate.add(inventory.output(table))
    if inventory.active:
        for table in cast(list[Object], inventory.active["tables"]):
            output = inventory.output(table)
            kind = str(table["kind"])
            if kind == "cells":
                key = "normalize_cells", "block/" + str(table["block"])
            elif kind in {"places", "canonical_cities", "place_to_city"}:
                key = "normalize_cells", "places/" + str(table["country"])
            else:
                matching = [
                    c
                    for c in candidates.values()
                    if c.stage == "lookups" and output.path in c.outputs
                ]
                if len(matching) != 1:
                    raise ValueError(
                        f"Active table has no unique ledger owner: {output.path}"
                    )
                key = matching[0].key
            if key not in candidates:
                raise ValueError(f"Active table lacks a completion record: {key}")
            candidates[key].add(output)
        candidate = Candidate("lookups", "manifest/current")
        candidate.add(
            file_output(inventory.root, inventory.active_prefix + "/manifest.json")
        )
        for raw in cast(
            list[Object], inventory.active.get("verification_artifacts", [])
        ):
            candidate.add(inventory.output(raw))
        candidates[candidate.key] = candidate
    # The current pilot receipt is selected by its input file hashes, not by mtime.
    gates = sorted((inventory.root / PILOT).glob("*gate.json"))
    for gate in gates:
        value = read_object(gate)
        records = [
            cast(Object, value[field])
            for field in ("normalization_manifest", "pilot_summary", "development")
        ]
        outputs = [inventory.output(record) for record in records]
        if any(
            not (inventory.root / output.path).exists()
            or sha256_file(inventory.root / output.path) != output.sha256
            for output in outputs
        ):
            continue
        candidate = Candidate("evaluate", "pilot")
        for output in outputs:
            candidate.add(output)
        candidate.add(
            file_output(inventory.root, gate.relative_to(inventory.root).as_posix())
        )
        if candidate.key in candidates:
            raise ValueError("More than one pilot review binds current evidence")
        candidates[candidate.key] = candidate
    if inventory.active and gates and ("evaluate", "pilot") not in candidates:
        raise ValueError("No pilot gate binds the retained pilot evidence")
