"""Measure real console process start to the first flushed reverse result."""

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import sysconfig
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
PACK = ROOT / "tests/fixtures/packs/core-sample"


def sample(command: list[str]) -> tuple[float, float]:
    started = time.perf_counter_ns()
    with subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        first = process.stdout.readline()
        elapsed = (time.perf_counter_ns() - started) / 1e6
        assert json.loads(first)["status"] == "matched"
        assert process.wait(timeout=30) == 0, process.stderr.read().decode()
        assert not process.stderr.read()
        total = (time.perf_counter_ns() - started) / 1e6
    return elapsed, total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    args = parser.parse_args()
    if args.iterations < 2:
        parser.error("Use at least two process launches")
    executable = Path(sysconfig.get_path("scripts")) / (
        "thereabouts.exe" if os.name == "nt" else "thereabouts"
    )
    manifest = json.loads((PACK / "manifest.json").read_text())
    digest = hashlib.sha256((PACK / "manifest.json").read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="cli-benchmark-", dir=ROOT / ".tmp") as tmp:
        store = Path(tmp)
        relative = Path("packs/core") / manifest["data_version"]
        shutil.copytree(PACK, store / relative)
        (store / "active.json").write_text(
            json.dumps(
                {
                    "data_version": manifest["data_version"],
                    "packs": {
                        "core": {
                            "path": relative.as_posix(),
                            "manifest_sha256": digest,
                        }
                    },
                }
            )
        )
        lookup = ["reverse", "--lat", "48.8566", "--lon", "2.3522"]
        command = [str(executable), "--data-dir", str(store), *lookup]
        first_launch = sample(command)
        for _ in range(2):
            sample(command)
        samples = [sample(command) for _ in range(args.iterations)]
    first = [v[0] for v in samples]
    total = [v[1] for v in samples]
    result: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "iterations": args.iterations,
        "warmup_launches": 3,
        "file_cache": "warm; each sample launches a new console process",
        "command": ["thereabouts", *lookup],
        "pack_manifest_sha256": digest,
        "first_launch_ms": first_launch[0],
        "first_result_median_ms": statistics.median(first),
        "first_result_p99_ms": sorted(first)[math.ceil(len(first) * 0.99) - 1],
        "total_median_ms": statistics.median(total),
        "first_result_samples_ms": first,
        "total_samples_ms": total,
    }
    path = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    measurements = json.loads(path.read_text())
    measurements["cli_startup"] = result
    path.write_text(json.dumps(measurements, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
