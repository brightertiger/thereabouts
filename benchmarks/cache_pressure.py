"""Measure shuffled place-cache misses independently from warm retained entries."""

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np

from thereabouts.client import Geocoder

from .read_path import profile


def measure(root: Path) -> list[dict[str, object]]:
    points = [(float(a), float(b)) for a, b in np.load(root / "shuffled.npy")[:5000]]
    reports = []
    # Stress budgets deliberately below this sample's measured ~8.8 MB working set.
    for budget in (0, 64 * 1024):
        with Geocoder(root / "pack", cache_bytes=budget) as geo:
            for _ in geo.reverse_columns(points):
                pass
            timings = []
            for point in points:
                start = time.perf_counter_ns()
                geo.reverse(*point)
                timings.append(time.perf_counter_ns() - start)
            reports.append(
                {
                    "budget_bytes": budget,
                    "scalar_median_ns": statistics.median(timings),
                    "scalar_p99_ns": sorted(timings)[4949],
                    "cache": geo.info()["cache"]["reverse"],
                    "profile": profile(geo, points, False),
                }
            )
    return reports


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(measure(args.sample), indent=2) + "\n")
