"""Measure scalar latency and column throughput on the committed real sample.

uv run python -m benchmarks.core_read_path --output docs/CLIENT_CORE_MEASUREMENTS.json
All documented new measurements originate here. Historical comparison figures
are explicitly identified as measurements of the older synthetic workload.
"""

import argparse
import json
import platform
import resource
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from thereabouts import Geocoder

ROOT = Path(__file__).resolve().parents[1]


def measure(iterations: int) -> dict[str, Any]:
    vectors = json.loads((ROOT / "tests/fixtures/core-sample-vectors.json").read_text())
    points = np.array(
        [
            case["request"]["values"]
            for case in vectors["cases"]
            if case["request"]["kind"] == "coordinates"
        ],
        dtype=np.float64,
    )
    rng = np.random.default_rng(20261003)
    indices = rng.integers(0, len(points), size=iterations)
    lat, lon = points[indices, 0], points[indices, 1]
    pack = ROOT / "tests/fixtures/packs/core-sample"
    with Geocoder(pack) as geo:
        for a, b in points:
            geo.reverse(lat=a, lon=b)
        durations = []
        for a, b in zip(lat, lon, strict=True):
            start = time.perf_counter_ns()
            geo.reverse(lat=a, lon=b)
            durations.append(time.perf_counter_ns() - start)
        rates = []
        for _ in range(7):
            batch_start = time.perf_counter()
            columns = geo.reverse_columns(lat, lon)
            elapsed = time.perf_counter() - batch_start
            assert len(columns["status"]) == iterations
            rates.append(iterations / elapsed)
    chip = (
        subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
        if platform.system() == "Darwin"
        else platform.machine()
    )
    memory = (
        int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
        if platform.system() == "Darwin"
        else None
    )
    return {
        "machine": dict(
            chip=chip,
            memory_bytes=memory,
            platform=platform.platform(),
            python=platform.python_version(),
        ),
        "workload": dict(
            pack="core-sample",
            iterations=iterations,
            coordinate_vectors=len(points),
            seed=20261003,
            pack_bytes=sum(p.stat().st_size for p in pack.iterdir() if p.is_file()),
        ),
        "scalar_median_us": statistics.median(durations) / 1000,
        "scalar_p99_us": float(np.percentile(durations, 99)) / 1000,
        "reverse_columns_points_per_second": statistics.median(rates),
        "reverse_columns_repeats": rates,
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if platform.system() == "Darwin" else 1024),
        "historical_reader": {
            "source": "CLIENT_STATUS.md at 3ade5da; benchmarks.read_path",
            "workload": "synthetic 308032 cells / 4176 places; not the real sample",
            "cython_scalar_median_us": 10.291,
            "python_scalar_median_us": 12.750,
            "cython_columns_points_per_second": 531994,
            "python_columns_points_per_second": 530437,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error("at least 100 iterations are required")
    result = measure(args.iterations)
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
