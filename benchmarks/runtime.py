"""Runtime-only process: mmap open, scalar tails, batch throughput and peak RSS."""

import argparse
import hashlib
import json
import platform
import resource
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from h3.api import basic_int as h3

from pyofflinegeocoder import Geocoder, Location


def scalar_times(
    lookup: Callable[[float, float], Location | None], pairs: list[tuple[float, float]]
) -> dict[str, float]:
    for pair in pairs[:1000]:
        lookup(*pair)
    elapsed = []
    for pair in pairs:
        started = time.perf_counter_ns()
        lookup(*pair)
        elapsed.append((time.perf_counter_ns() - started) / 1000)
    return {
        "median_us": float(np.median(elapsed)),
        "p99_us": float(np.percentile(elapsed, 99)),
    }


def measure(path: Path, points_file: Path, count: int) -> dict[str, Any]:
    points = np.load(points_file, allow_pickle=False)[:count]
    pairs = [(float(lat), float(lon)) for lat, lon in points]
    if not pairs:
        raise ValueError("runtime workload must contain points")
    opens = []
    for _ in range(20):
        started = time.perf_counter_ns()
        with Geocoder(path):
            opens.append((time.perf_counter_ns() - started) / 1e6)
    with Geocoder(path) as geocoder:
        started = time.perf_counter_ns()
        geocoder.reverse(*pairs[0])
        first_ms = (time.perf_counter_ns() - started) / 1e6
        scalar = scalar_times(geocoder.reverse, pairs)
        batches = []
        for _ in range(3):
            started_batch = time.perf_counter()
            assert sum(1 for _ in geocoder.reverse_many(pairs)) == len(pairs)
            batches.append(time.perf_counter() - started_batch)
        manifest = geocoder.info()
    runtime_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
        1 if sys.platform == "darwin" else 1024
    )
    # A fresh instance gives both paths the same 1,000-point name-cache warmup.
    with Geocoder(path) as geocoder:
        baseline = scalar_times(
            lambda lat, lon: next(geocoder.reverse_many([(lat, lon)])), pairs
        )
    return {
        "snapshot_id": manifest["snapshot_id"],
        "manifest_sha256": hashlib.sha256(
            (path / "manifest.json").read_bytes()
        ).hexdigest(),
        "resolution": manifest["resolution"],
        "warm_open_median_ms": float(np.median(opens)),
        "first_query_ms_excluding_open": first_ms,
        "scalar": scalar,
        "single_point_vector_baseline": baseline,
        "batch_points_per_second": len(pairs) / float(np.median(batches)),
        "sample_count": len(pairs),
        "points_sha256": hashlib.sha256(points.tobytes()).hexdigest(),
        "peak_process_rss_bytes": runtime_peak,
        "pack_bytes": sum(p.stat().st_size for p in path.iterdir()),
        "cache": (
            "warm OS cache; each scalar path has 1000 warmup calls on a fresh instance"
        ),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "h3": h3.versions(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/h3-world"))
    parser.add_argument(
        "--points", type=Path, default=Path("data/benchmarks/points.npy")
    )
    parser.add_argument("--count", type=int, default=10000)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/runtime.json"))
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("count must be positive")
    result = measure(args.data, args.points, args.count)
    text = json.dumps(result, indent=2) + "\n"
    args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
