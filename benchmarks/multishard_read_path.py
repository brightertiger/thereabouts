"""Measure random catalogue misses over 256 locally generated small shards.

uv run python -m benchmarks.multishard_read_path --record before
Repeat with --record after after rebuilding the extension. Both runs use the
same seed, pack and number of lookups; the script alone records the measurements.
"""

import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np

from benchmarks.core_read_path import ROOT, current_rss, workload
from thereabouts import Geocoder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", choices=["before", "after"], required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    )
    args = parser.parse_args()
    pack = ROOT / ".tmp/core-multishard"
    points_file = ROOT / ".tmp/multishard-points.json"
    if not points_file.exists():
        with points_file.open("w") as stream:
            subprocess.run(
                [
                    "cargo",
                    "run",
                    "--quiet",
                    "--manifest-path",
                    str(ROOT / "core/Cargo.toml"),
                    "-p",
                    "thereabouts-core",
                    "--example",
                    "multishard",
                    "--",
                    str(pack),
                ],
                stdout=stream,
                check=True,
            )
    points = np.asarray(json.loads(points_file.read_text()), dtype=np.float64)
    rng = np.random.default_rng(20261003)
    queries = points[rng.integers(0, len(points), size=100_000)]
    rss = current_rss()
    start = time.perf_counter()
    with Geocoder(pack) as geo:
        opened = time.perf_counter() - start
        delta = current_rss() - rss
        result = workload(geo, queries)
    result.update(
        open_seconds=opened,
        open_rss_delta_bytes=delta,
        catalogue_shards=256,
        places=len(points),
        pack_bytes=sum(p.stat().st_size for p in pack.iterdir()),
        seed=20261003,
    )
    data = json.loads(args.output.read_text())
    data.setdefault("multishard", {})[args.record] = result
    args.output.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
