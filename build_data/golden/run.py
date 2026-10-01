"""Resumable block scheduler; unfinished neighbouring countries are hard waits."""

from __future__ import annotations

import time

from build_data.acquire import Workspace
from build_data.acquire.io import write_json
from build_data.acquire.ledger import read_units
from build_data.reconcile.common import Row

from . import cells
from .inputs import Inputs, verify_record
from .workers import execute


def committed(
    workspace: Workspace, inputs: Inputs, plan: list[Row], implementation: str
) -> dict[str, Row]:
    expected = {r["root"]: r["countries"] for r in plan}
    result = {}
    fingerprints = {}
    for unit in read_units(workspace.ledger_path, "golden.cells"):
        root, required = unit["unit_id"], unit["metadata"]["countries"]
        if (
            root not in expected
            or required != expected[root]
            or not set(required) <= inputs.countries.keys()
        ):
            continue
        key = tuple(required)
        if key not in fingerprints:
            fingerprints[key] = cells.digest(inputs, required, implementation)
        if unit["inputs_hash"] != fingerprints[key]:
            continue
        try:
            for record in unit["outputs"]:
                verify_record(record)
        except (OSError, ValueError):
            continue  # The scheduler rebuilds a missing or corrupt unit.
        result[root] = unit["metadata"]
    return result


def progress(plan: list[Row], inputs: Inputs, built: dict[str, Row]) -> Row:
    waiting = [r for r in plan if not set(r["countries"]) <= inputs.countries.keys()]
    return {
        "total_blocks": len(plan),
        "built_blocks": len(built),
        "waiting_blocks": len(waiting),
        "remaining_blocks": len(plan) - len(built),
        "ready_remaining_blocks": len(plan) - len(built) - len(waiting),
        "waiting_countries": sorted(
            {cc for r in waiting for cc in r["countries"] if cc not in inputs.countries}
        ),
        "cells_completed": len(built) == len(plan),
        "completed": False,
        "enumerated_centres": sum(r["enumerated"] for r in built.values()),
        "labelled_centres": sum(r["labelled"] for r in built.values()),
        "eligible_centres": sum(r["eligible"] for r in built.values()),
    }


def build_blocks(
    workspace: Workspace,
    inputs: Inputs,
    plan: list[Row],
    *,
    selected: list[str] | None = None,
    limit: int | None = None,
    verify: bool = False,
    workers: int = 1,
) -> tuple[dict[str, Row], Row]:
    implementation = cells.builder()
    built = committed(workspace, inputs, plan, implementation)
    started = time.monotonic()
    selected_blocks = [
        r
        for r in plan
        if selected is None or set(selected).intersection(r["countries"])
    ]
    print(
        f"cells: {len(built):,} committed; {len(selected_blocks):,} selected",
        flush=True,
    )
    pending = [
        r
        for r in selected_blocks
        if set(r["countries"]) <= inputs.countries.keys()
        and (
            r["root"] not in built
            or (
                verify
                and not built[r["root"]].get("checks", {}).get("exhaustive_centres")
            )
        )
    ]
    if limit is not None:
        pending = pending[:limit]
    for made, (root, stats) in enumerate(
        execute(workspace, inputs, pending, implementation, verify, workers), start=1
    ):
        built[root] = stats
        if made % 20 == 0:
            state = progress(plan, inputs, built)
            state.update(
                stage="cells",
                elapsed_seconds=time.monotonic() - started,
                selected=selected,
            )
            write_json(workspace.work / "golden" / "run.json", state)
            print(
                f"cells: +{made:,}; world {len(built):,}/{len(plan):,}; "
                f"{state['waiting_blocks']:,} waiting; "
                f"{time.monotonic() - started:.1f}s",
                flush=True,
            )
            if cells.builder() != implementation:
                raise RuntimeError(
                    "Golden cell code changed during the build; "
                    "resume with the same command"
                )
    state = progress(plan, inputs, built)
    subset_built = {
        r["root"]: built[r["root"]] for r in selected_blocks if r["root"] in built
    }
    state["selection"] = progress(selected_blocks, inputs, subset_built)
    state["resolutions"] = {
        str(level): sum(r["resolutions"].get(str(level), 0) for r in built.values())
        for level in range(3, 9)
    }
    write_json(workspace.work / "golden" / "run.json", state)
    return built, state
