"""Compare thread and process unit workers: wall time and CPU use per core.

Two workloads run in scratch workspaces: a pure-Python stage (24 units of
string and integer work) and the real reconcile-to-lookups engines on the
two-country synthetic graph widened to 19 blocks.
"""

import argparse
import json
import os
import resource
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Direct execution puts tests/benchmarks/, rather than the repository, on sys.path.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import h3

from pipeline.runtime.jsonio import atomic_output
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context, Unit
from tests.pipeline.geographic_fixtures import build, geographic_graph, source_receipts
from tests.pipeline.helpers import SyntheticStage, context


@dataclass
class Python(SyntheticStage):
    """A unit of interpreter-bound work, like parsing rows or labelling cells."""

    rounds: int = 3_000_000

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        total = 0
        for value in range(self.rounds):
            total = (total + len(str(value * 31))) % 1_000_003
        path = ctx.root / self.name / unit.recipe.unit_id
        with atomic_output(path) as temporary:
            temporary.write_text(str(total))
        return [path]


def cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def measure(work: Callable[[Path], None]) -> dict[str, float]:
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
        cpu, wall = cpu_seconds(), time.monotonic()
        work(Path(directory))
        wall, cpu = time.monotonic() - wall, cpu_seconds() - cpu
    return {
        "wall_s": round(wall, 2),
        "cpu_s": round(cpu, 2),
        "cores": round(cpu / wall, 2),
    }


def python_stage(workers: int, executor: str) -> Callable[[Path], None]:
    def work(root: Path) -> None:
        stage = Python("python", [Recipe("python", str(i)) for i in range(24)])
        with Ledger(root, None, readonly=False) as ledger:
            ctx = context(root, ledger)
            ctx.config.resources.workers = workers
            ctx.config.resources.executor = executor
            run(ctx, [stage])

    return work


def engines(workers: int, executor: str) -> Callable[[Path], None]:
    def work(root: Path) -> None:
        with Ledger(root, None, readonly=False) as ledger:
            ctx, normalized = source_receipts(root, ledger, wide=True)
            centre = h3.latlng_to_cell(0, 0, 3)
            ctx.config.engines.blocks = sorted(h3.grid_disk(centre, 2))
            ctx.config.resources.workers = workers
            ctx.config.resources.executor = executor
            build(ctx, geographic_graph(ctx, normalized))

    return work


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, nargs="+", default=[4, 7])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results: dict[str, Any] = {"load_before": os.getloadavg()}
    for name, workload in (("python", python_stage), ("engines", engines)):
        results[name] = {"1/thread": measure(workload(1, "thread"))}
        for workers in args.workers:
            for executor in ("thread", "process"):
                key = f"{workers}/{executor}"
                results[name][key] = measure(workload(workers, executor))
                print(name, key, results[name][key], flush=True)
    results["load_after"] = os.getloadavg()
    text = json.dumps(results, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
