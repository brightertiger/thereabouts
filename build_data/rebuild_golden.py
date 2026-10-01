"""Resume a gated world reconciliation, then the dependent golden build."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.acquire.runtime import single_run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--sample-gate", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    work = workspace.work / "v1"
    work.mkdir(parents=True, exist_ok=True)
    commands = [
        (
            "reconcile",
            [
                sys.executable,
                "-m",
                "build_data.reconcile",
                "--world",
                "--data-dir",
                str(workspace.root),
                "--improvement-gate",
                str(args.sample_gate.resolve()),
            ],
            workspace.work / "reconcile/run.json",
        ),
        (
            "golden",
            [
                sys.executable,
                "-m",
                "build_data.golden",
                "run",
                "--data-dir",
                str(workspace.root),
                "--workers",
                str(args.workers),
            ],
            workspace.work / "golden/run.json",
        ),
    ]
    with single_run(workspace, "rebuild-golden"):
        for stage, command, signal in commands:
            log = work / f"{stage}-world.log"
            state = {
                "completed": False,
                "stage": stage,
                "pid": os.getpid(),
                "command": command,
                "log": str(log),
                "started_at": datetime.now(UTC).isoformat(),
            }
            write_json(work / "rebuild.json", state)
            with log.open("a") as stream:
                result = subprocess.run(
                    command, stdout=stream, stderr=subprocess.STDOUT, check=False
                )
            if result.returncode or not read_json(signal).get("completed"):
                state.update(failed=True, returncode=result.returncode)
                write_json(work / "rebuild.json", state)
                raise SystemExit(
                    f"{stage} incomplete; inspect {log} and resume this command"
                )
        write_json(
            work / "rebuild.json",
            {
                "completed": True,
                "stage": "complete",
                "finished_at": datetime.now(UTC).isoformat(),
            },
        )


if __name__ == "__main__":
    main()
