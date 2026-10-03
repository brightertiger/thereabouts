"""Measure standalone optional packs built from synthetic joined source rows."""

import argparse
import json
import platform
import resource
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from pipeline.engines.serving.export import export
from tests.codes.fixtures import snapshot
from thereabouts.client import Geocoder
from thereabouts.results import Resolution


def measure(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=False)
    manifest, release = snapshot(root / "input")
    results = {}
    for family in ("postal", "airports"):
        started = time.perf_counter()
        path = export(manifest, release, root / family, family=family, shard_bytes=2048)
        elapsed = time.perf_counter() - started
        with Geocoder(path, verify=True) as geo:
            query: Callable[[], Resolution] = (
                (lambda: geo.postal("AMB", country="AA"))
                if family == "postal"
                else (lambda: geo.airport("ZZZ", scheme="iata"))
            )
            first = time.perf_counter_ns()
            expected = query()
            first_ns = time.perf_counter_ns() - first
            timings = []
            for _ in range(5000):
                before = time.perf_counter_ns()
                actual = query()
                timings.append(time.perf_counter_ns() - before)
            assert actual == expected
            results[family] = {
                "info": geo.info(),
                "export_seconds": elapsed,
                "installed_bytes": sum(
                    p.stat().st_size for p in path.rglob("*") if p.is_file()
                ),
                "first_lookup_ns": first_ns,
                "warm_median_ns": statistics.median(timings),
                "warm_p99_ns": sorted(timings)[4949],
                "candidates": len(expected.candidates),
            }
    return {
        "machine": platform.platform(),
        "python": platform.python_version(),
        "results": results,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "limitations": [
            "Synthetic seven postal and four airport rows, two-candidate warm queries.",
            "No geographic quality, cold-disk or world capacity claim.",
            "No network access; queries omit JSON serialization.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = measure(args.output)
    (args.output / "measurements.json").write_text(json.dumps(value, indent=2) + "\n")
