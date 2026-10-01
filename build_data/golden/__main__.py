"""Build or resume golden Parquet tables in the explicitly selected workspace."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.acquire.ledger import read_units
from build_data.acquire.runtime import single_run

from . import joins, places, static
from .blocks import Plan, cache_path
from .inputs import discover
from .metrics import measure
from .planning import Dependencies, inventory
from .publish import publish
from .quality import evaluate
from .run import build_blocks
from .storage import DiskBudgetExceeded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("run", "pilot", "static", "plan", "lookups", "status"),
        nargs="?",
        default="run",
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--countries", nargs="+")
    parser.add_argument("--limit-blocks", type=int)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=300)
    parser.add_argument("--verify-blocks", action="store_true")
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    work = workspace.work / "golden"
    if args.command == "status":
        value = (
            read_json(work / "run.json")
            if (work / "run.json").exists()
            else {"completed": False, "stage": "not started"}
        )
        value["checkpoint_blocks"] = len(
            read_units(workspace.ledger_path, "golden.cells")
        )
        print(json.dumps(value, indent=2))
        return
    with single_run(workspace, "golden"):
        while True:
            try:
                completed = cycle(workspace, args)
            except DiskBudgetExceeded as error:
                if not args.watch:
                    raise
                state = read_json(work / "run.json")
                state.update(
                    completed=False, stage="waiting for disk", error=str(error)
                )
                write_json(work / "run.json", state)
                print(str(error), flush=True)
                completed = False
            if not args.watch or completed:
                return
            # This is the detached worker's polling loop, independent of the
            # interactive agent. No reconciliation locks or markers are touched.
            time.sleep(max(1, args.poll_seconds))


def cycle(workspace: Workspace, args: argparse.Namespace) -> bool:
    work = workspace.work / "golden"
    write_json(work / "run.json", {"completed": False, "stage": "verifying inputs"})
    inputs = discover(workspace)
    country_inventory = inventory(workspace, inputs)
    inputs.expected = set(country_inventory["expected"])
    plan = Plan(
        cache_path(work),
        Dependencies(country_inventory, inputs.policy["offshore_m"]),
    )
    try:
        if args.command != "static":
            plan.create()
        block_plan = plan.rows()
    finally:
        plan.close()
    if args.command == "plan":
        return True
    publish(workspace, inputs, [], {"completed": False, "stage": "exporting places"})
    independent = places.export(workspace, inputs) + static.export(workspace, inputs)
    publish(
        workspace,
        inputs,
        independent,
        {
            "completed": False,
            "stage": "static" if args.command == "static" else "building",
        },
    )
    if args.command == "static":
        write_json(work / "run.json", {"completed": False, "stage": "static"})
        return True
    selected = args.countries or (
        ["BE", "NL", "LU", "AU"] if args.command == "pilot" else None
    )
    if args.command == "lookups":
        from .cells import builder
        from .run import committed, progress

        built = committed(workspace, inputs, block_plan, builder())
        state = progress(block_plan, inputs, built)
    else:
        built, state = build_blocks(
            workspace,
            inputs,
            block_plan,
            selected=selected,
            limit=args.limit_blocks,
            verify=args.verify_blocks or args.command == "pilot",
            workers=args.workers,
        )
    tables = [r["table"] for r in built.values()]
    lookup_tables = joins.export(workspace, tables)
    checks = evaluate(tables, inputs)
    checks["integrity"] = measure(workspace, independent, tables)
    state["countries_ready"] = len(inputs.countries)
    state["countries_expected"] = len(country_inventory["expected"])
    state["countries_waiting"] = sorted(inputs.expected - inputs.countries.keys())
    state["completed"] = (
        state["cells_completed"]
        and set(country_inventory["expected"]) <= inputs.countries.keys()
        and checks["integrity"].get("missing_cell_place_ids", 0) == 0
        and checks["integrity"].get("duplicate_place_ids", 0) == 0
        and checks["integrity"].get("missing_parent_rows", 0) == 0
        and checks["integrity"].get("missing_sovereign_rows", 0) == 0
    )
    publish(workspace, inputs, independent + tables + lookup_tables, state, checks)
    write_json(work / "run.json", state)
    if args.command == "pilot":
        write_json(
            work / "pilot.json",
            {
                "selection": state["selection"],
                "checks": checks,
                "blocks": [
                    r
                    for r in built.values()
                    if set(selected or []).intersection(r["countries"])
                ],
            },
        )
    print(json.dumps(state), flush=True)
    return bool(state["completed"])


if __name__ == "__main__":
    main()
