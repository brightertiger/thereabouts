"""Measure public reverse results separately from analytic columns on a local pack."""

import argparse
import platform
import resource
import statistics
import sys
import time
from pathlib import Path

from h3.api import basic_int as h3

from thereabouts.client import Geocoder
from thereabouts.packs.jsonio import canonical
from thereabouts.reading.backend import Backend


def measure(pack: Path, backend: Backend = "auto") -> dict[str, object]:
    roots = [
        h3.latlng_to_cell(a, b, 3)
        for a, b in ((12.97, 77.59), (0, 0), (45, 45), (-45, -45))
    ]
    points = [
        h3.cell_to_latlng(cell)
        for root in roots
        for cell in h3.cell_to_children(root, 8)[::67]
    ]
    start: float = time.perf_counter_ns()
    geo = Geocoder(pack, backend=backend)
    opened = time.perf_counter_ns() - start
    with geo:
        start = time.perf_counter_ns()
        geo.reverse(*points[0])
        first = time.perf_counter_ns() - start
        timings = []
        for index in range(10000):
            start = time.perf_counter_ns()
            geo.reverse(*points[index % len(points)])
            timings.append(time.perf_counter_ns() - start)
        queries = (points * 10)[:10000]
        start = time.perf_counter()
        for _ in geo.reverse_many(queries):
            pass
        batch = time.perf_counter() - start
        start = time.perf_counter()
        for _ in geo.reverse_columns(queries):
            pass
        columns = time.perf_counter() - start
        info = geo.info()
    start = time.perf_counter()
    with Geocoder(pack, verify=True):
        pass
    verification = time.perf_counter() - start
    return {
        "backend": info["backend"],
        "machine": platform.platform(),
        "processor": platform.machine(),
        "python": platform.python_version(),
        "h3": h3.versions(),
        "manifest_sha256": info["packs"]["reverse"]["manifest_sha256"],
        "installed_bytes": sum(
            p.stat().st_size for p in pack.rglob("*") if p.is_file()
        ),
        "open_ns": opened,
        "first_lookup_ns": first,
        "warm_scalar_median_ns": statistics.median(timings),
        "warm_scalar_p99_ns": sorted(timings)[9899],
        "batch_points_per_second": len(queries) / batch,
        "numeric_columns_points_per_second": len(queries) / columns,
        "full_verification_seconds": verification,
        "peak_process_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if sys.platform == "darwin" else 1024),
        "limitations": [
            "Synthetic four-block clustered queries, tiny repeated catalogue.",
            "No page cache eviction; open/first lookup are not cold-disk measurements.",
            "Scalar/batch include H3 and results; numeric columns omit place decoding.",
            "No world access, accuracy or representative catalogue pressure measured.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = canonical(measure(args.pack)) + b"\n"
    args.output.write_bytes(report)
    print(report.decode(), end="")
