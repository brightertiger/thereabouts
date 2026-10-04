"""Measure scalar latency and column throughput on the committed real sample.

uv run python -m benchmarks.core_read_path \
    --output docs/measurements/CLIENT_CORE_MEASUREMENTS.json
Reverse measurements originate here; companion scripts record forward and scale work.
Historical comparison figures
are explicitly identified as measurements of the older synthetic workload.
"""

import argparse
import json
import os
import platform
import resource
import statistics
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

import h3
import numpy as np

from thereabouts import Geocoder

ROOT = Path(__file__).resolve().parents[1]


def warm_file_cache(pack: Path) -> None:
    """Preload file bytes in bounded chunks without populating any decoded cache."""
    buffer = bytearray(65536)
    for path in sorted(pack.iterdir()):
        if path.is_file():
            with path.open("rb") as stream:
                while stream.readinto(buffer):
                    pass


def current_rss() -> int:
    """Resident bytes immediately around open, excluding workload allocation."""
    return 1024 * int(
        subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], text=True)
    )


def random_points(pack: Path, count: int) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Uniformly choose an inventoried r3 block, then rejection-sample its bounds."""
    blocks = []
    for path in sorted(pack.glob("cells-*.bin")):
        with path.open("rb") as stream:
            header = stream.read(64)
            offset, _, rows = struct.unpack_from("<QQQ", header, 40)
            stream.seek(offset)
            for _ in range(rows):
                block = struct.unpack_from("<I", stream.read(40))[0]
                base, digits = divmod(block, 343)
                cell = (1 << 59) | (3 << 52) | (base << 45) | ((1 << 45) - 1)
                for resolution in range(3, 0, -1):
                    digits, digit = divmod(digits, 7)
                    shift = 3 * (15 - resolution)
                    cell = (cell & ~(7 << shift)) | (digit << shift)
                blocks.append(h3.int_to_str(cell))
    rng = np.random.default_rng(20261003)
    points = []
    boundaries = [np.asarray(h3.cell_to_boundary(cell)) for cell in blocks]
    for index in rng.integers(0, len(blocks), size=count):
        boundary = boundaries[index]
        low, high = boundary.min(axis=0), boundary.max(axis=0)
        while True:
            lat, lon = rng.uniform(low, high)
            if h3.latlng_to_cell(lat, lon, 3) == blocks[index]:
                points.append((lat, lon))
                break
    return np.asarray(points, dtype=np.float64)


def workload(
    geo: Geocoder, points: np.ndarray[Any, np.dtype[np.float64]]
) -> dict[str, Any]:
    lat, lon = points[:, 0], points[:, 1]
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
        assert len(columns["status"]) == len(points)
        rates.append(len(points) / elapsed)
    return {
        "points": len(points),
        "scalar_median_us": statistics.median(durations) / 1000,
        "scalar_p99_us": float(np.percentile(durations, 99)) / 1000,
        "reverse_columns_points_per_second": statistics.median(rates),
        "reverse_columns_repeats": rates,
    }


def measure(iterations: int) -> dict[str, Any]:
    pack = ROOT / "tests/fixtures/packs/core-sample"
    warm_file_cache(pack)
    rss_before = current_rss()
    start = time.perf_counter()
    geo = Geocoder(pack)
    open_seconds = time.perf_counter() - start
    open_rss_delta_bytes = current_rss() - rss_before
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
    with geo:
        for a, b in points:
            geo.reverse(lat=a, lon=b)
        hot = workload(geo, points[indices])
        random = workload(geo, random_points(pack, 100_000))
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
            filesystem_cache="preloaded",
            iterations=iterations,
            coordinate_vectors=len(points),
            seed=20261003,
            pack_bytes=sum(p.stat().st_size for p in pack.iterdir() if p.is_file()),
        ),
        "open_seconds": open_seconds,
        "open_rss_delta_bytes": open_rss_delta_bytes,
        "cache_hot": hot,
        "random": random,
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
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error("at least 100 iterations are required")
    result = measure(args.iterations)
    if args.output and args.output.exists():
        previous = json.loads(args.output.read_text())
        for key in ("multishard", "before_names"):
            if key in previous:
                result[key] = previous[key]
        result.setdefault(
            "before_names",
            {
                key: previous[key]
                for key in (
                    "open_seconds",
                    "open_rss_delta_bytes",
                    "cache_hot",
                    "random",
                )
                if key in previous
            },
        )
        if "before_lazy_open" in previous:
            result["before_lazy_open"] = previous["before_lazy_open"]
        result["after_lazy_open"] = previous.get(
            "after_lazy_open",
            {
                key: previous[key]
                for key in (
                    "open_seconds",
                    "open_rss_delta_bytes",
                    "cache_hot",
                    "random",
                )
                if key in previous
            },
        )
        # Preserve other benchmark series when refreshing only the reverse path.
        result = previous | result
    if args.baseline:
        result["before_lazy_open"] = json.loads(args.baseline.read_text())
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
