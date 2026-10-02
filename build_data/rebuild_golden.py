"""Resume the complete acquired-source to normalized-dataset build chain."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.__main__ import ADAPTERS
from build_data.acquire.io import write_json
from build_data.acquire.manifests import load_manifest
from build_data.acquire.runtime import single_run
from build_data.cities.common import policy
from build_data.golden.inputs import discover
from build_data.rebuild_stages import completed_base, reconciled


class Controller:
    """Log each resumable stage; a failed stage leaves its own checkpoints intact."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.work = workspace.work / "rebuild"
        self.work.mkdir(parents=True, exist_ok=True)

    def run(self, stage: str, module: str, *arguments: str) -> None:
        """Run a stage; fail visibly before starting its dependents."""
        command = [
            sys.executable,
            "-m",
            module,
            *arguments,
            "--data-dir",
            str(self.workspace.root),
        ]
        log = self.work / f"{stage}.log"
        state = {
            "completed": False,
            "stage": stage,
            "pid": os.getpid(),
            "command": command,
            "log": str(log),
            "started_at": datetime.now(UTC).isoformat(),
        }
        write_json(self.work / "run.json", state)
        print(f"{stage}: {log}", flush=True)
        with log.open("a") as stream:
            result = subprocess.run(
                command, stdout=stream, stderr=subprocess.STDOUT, check=False
            )
        if result.returncode:
            write_json(
                self.work / "run.json",
                {**state, "failed": True, "returncode": result.returncode},
            )
            raise SystemExit(f"{stage} failed; inspect {log}, then resume this command")

    def upstream(self, sample_gate: Path | None, workers: int) -> None:
        """Acquire missing inputs and checkpoint the verified base cells."""
        for source in ADAPTERS:
            if (self.workspace.normalized(source) / "manifest.json").exists():
                load_manifest(self.workspace, source)
            else:
                self.run("acquire-" + source, "build_data.acquire", source)
        inputs = reconciled(self.workspace)
        if inputs is None:
            self.run("reconcile-pilot", "build_data.reconcile")
            args = ["--world"]
            if sample_gate:
                args.extend(["--improvement-gate", str(sample_gate.resolve())])
            self.run("reconcile-world", "build_data.reconcile", *args)
            inputs = discover(self.workspace)
        if completed_base(self.workspace, inputs) is None:
            self.run(
                "base-cells", "build_data.golden", "run", "--workers", str(workers)
            )
            if completed_base(self.workspace, inputs) is None:
                raise ValueError("Base stage did not complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--sample-gate", type=Path)
    parser.add_argument("--gate", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--through", choices=("pilot", "world", "publish"), default="world"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--review", type=Path, help="Examined final boundary-loss exceptions"
    )
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    output = (args.output or workspace.root / "golden-v2").resolve()
    gate = (args.gate or workspace.work / "v2-pilot/gate.json").resolve()
    controller = Controller(workspace)
    with single_run(workspace, "rebuild-golden"):
        controller.upstream(args.sample_gate, args.workers)
        countries = policy()["pilot"]
        controller.run("city-pilot", "build_data.cities", "--countries", *countries)
        controller.run(
            "pilot-quality",
            "build_data.cities.pilot",
            "--output",
            str(workspace.work / "v2-pilot"),
        )
        controller.run("pilot-dev", "build_data.cities.dev")
        controller.run("pilot-blocks", "build_data.normalize_cells.pilot_blocks")
        if args.through != "pilot":
            controller.run(
                "normalize-world",
                "build_data.normalize_cells",
                "run",
                "--output",
                str(output),
                "--gate",
                str(gate),
            )
            review = ["--review", str(args.review.resolve())] if args.review else []
            controller.run(
                "verify-world",
                "build_data.normalize_cells",
                "verify",
                "--output",
                str(output),
                *review,
            )
            if args.through == "publish":
                from build_data.normalize_cells.publish import activate

                activate(workspace, output)
        write_json(
            controller.work / "run.json",
            {
                "completed": True,
                "stage": args.through,
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )


if __name__ == "__main__":
    main()
