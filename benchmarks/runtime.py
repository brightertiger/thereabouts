"""Reproduce build, warm-open, scalar and streaming batch measurements."""

import argparse
import json
import platform
import resource
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
import shapely

from pyofflinegeocoder import Geocoder


def land_points(geocoder: Geocoder, count: int, seed: int) -> list[tuple[float, float]]:
    rng = np.random.default_rng(seed)
    points: list[tuple[float, float]] = []
    while len(points) < count:
        longitude = float(rng.uniform(-180, 180))
        latitude = float(np.rad2deg(np.arcsin(rng.uniform(-1, 1))))
        if (
            geocoder.reverse(latitude, longitude, include_place=False).land_status
            == "inside_mask"
        ):
            points.append((latitude, longitude))
    return points


def measure(path: Path, count: int, seed: int) -> dict[str, Any]:
    opens: list[float] = []
    for _ in range(20):
        started = time.perf_counter_ns()
        geocoder = Geocoder(path)
        opens.append((time.perf_counter_ns() - started) / 1e6)
        geocoder.close()
    with Geocoder(path) as geocoder:
        started = time.perf_counter_ns()
        geocoder.reverse(50.85, 4.35)
        first_result_ms = (time.perf_counter_ns() - started) / 1e6
        points = land_points(geocoder, count, seed)
        for pair in points[:1000]:
            geocoder.reverse(*pair)
        timings = np.empty(count)
        statuses: dict[str, int] = {}
        for index, pair in enumerate(points):
            started = time.perf_counter_ns()
            result = geocoder.reverse(*pair)
            timings[index] = (time.perf_counter_ns() - started) / 1000
            statuses[result.place_status] = statuses.get(result.place_status, 0) + 1
        batch_started = time.perf_counter()
        batch_count = sum(1 for _ in geocoder.reverse_many(iter(points)))
        batch_seconds = time.perf_counter() - batch_started
        info = geocoder.info()
    return {
        "snapshot_id": info.snapshot_id,
        "policy_id": info.policy_id,
        "pack_bytes": sum(p.stat().st_size for p in path.iterdir()),
        "pack_allocated_bytes": sum(p.stat().st_blocks * 512 for p in path.iterdir()),
        "warm_open_median_ms": float(np.median(opens)),
        "warm_open_p99_ms": float(np.percentile(opens, 99)),
        "open_repetitions": len(opens),
        "first_query_ms_excluding_open": first_result_ms,
        "scalar_median_us": float(np.median(timings)),
        "scalar_p99_us": float(np.percentile(timings, 99)),
        "batch_points_per_second": batch_count / batch_seconds,
        "batch_seconds": batch_seconds,
        "sample_count": count,
        "seed": seed,
        "sampling": (
            "area-uniform sphere rejection sampled against normalized "
            "terrestrial mask; includes Antarctica"
        ),
        "place_status_counts": statuses,
        "cutoff_km": 50.0,
        "cache_state": (
            "warm OS cache; all indexes warmed before scalar/batch measurements"
        ),
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": processor(),
            "numpy": np.__version__,
            "scipy": version("scipy"),
            "shapely": shapely.__version__,
            "concurrency": 1,
        },
    }


def processor() -> str:
    if sys.platform == "darwin":
        return subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
    return platform.processor()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/world"))
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument(
        "--build", action="store_true", help="build a new pack before benchmarking"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.count < 10_000:
        parser.error("at least 10,000 points are required")
    build_report = None
    if args.build:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build_data",
                "--output",
                str(args.data),
                "--cache",
                str(args.cache),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        build_report = json.loads(completed.stdout)
    result = measure(args.data, args.count, args.seed)
    result["build"] = build_report
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
