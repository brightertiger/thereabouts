"""Measure cache misses against one 25,000-place shard before and after R1."""

import argparse
import json
import subprocess
import time

import numpy as np

from benchmarks.catalogue_spans import spans
from benchmarks.core_read_path import ROOT, current_rss, warm_file_cache
from thereabouts import Geocoder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", choices=["before", "after"], required=True)
    args = parser.parse_args()
    pack = ROOT / ".tmp/core-single-shard"
    points_file = ROOT / ".tmp/single-shard-points.json"
    if not points_file.exists():
        with points_file.open("w") as stream:
            subprocess.run(
                [
                    "cargo",
                    "run",
                    "--release",
                    "--quiet",
                    "--manifest-path",
                    str(ROOT / "core/Cargo.toml"),
                    "-p",
                    "thereabouts-core",
                    "--example",
                    "multishard",
                    "--",
                    str(pack),
                    "single",
                ],
                stdout=stream,
                check=True,
            )
    points = np.asarray(json.loads(points_file.read_text()), dtype=np.float64)
    indices = np.random.default_rng(20261003).permutation(len(points))[:2000]
    queries = points[indices]
    times = []
    warm_file_cache(pack)
    rss = current_rss()
    start = time.perf_counter()
    with Geocoder(pack) as geo:
        opened = time.perf_counter() - start
        delta = current_rss() - rss
        # Every query is a distinct place; no warming hides catalogue misses.
        for lat, lon in queries:
            begin = time.perf_counter_ns()
            answer = geo.reverse(lat=float(lat), lon=float(lon))
            times.append((time.perf_counter_ns() - begin) / 1000)
            assert answer.status == "matched"
    with Geocoder(pack) as geo:
        start = time.perf_counter()
        geo.reverse_columns(lat=queries[:, 0].copy(), lon=queries[:, 1].copy())
        batch = len(queries) / (time.perf_counter() - start)
    result = {
        "scope": (
            "preloaded file cache; 2000 distinct random places; "
            "fresh decoded caches for scalar and batch"
        ),
        "scalar_median_us": float(np.median(times)),
        "scalar_p99_us": float(np.percentile(times, 99)),
        "reverse_columns_points_per_second": batch,
        "open_seconds": opened,
        "open_rss_delta_bytes": delta,
        "pack_bytes": sum(p.stat().st_size for p in pack.iterdir()),
        "single_shard_spans": spans(pack),
        "real_sample_spans": spans(ROOT / "tests/fixtures/packs/core-sample"),
    }
    path = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(path.read_text())
    series = data.setdefault("single_shard", {})
    if args.record in series:
        series.setdefault(f"{args.record}_history", []).append(series[args.record])
    series[args.record] = result
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
