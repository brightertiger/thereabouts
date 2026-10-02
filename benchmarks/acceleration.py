"""Compare the native reconstruction kernel with the Python reference end to end."""

import argparse
import cProfile
import statistics
import time
from pathlib import Path
from types import CodeType

from h3.api import basic_int as h3

from benchmarks.client import measure
from thereabouts.client import Geocoder
from thereabouts.packs.address import address
from thereabouts.packs.jsonio import canonical
from thereabouts.reading.backend import Backend, select


def compare(pack: Path) -> dict[str, object]:
    if select("auto")[0] != "cython":
        raise RuntimeError("Build the extension before measuring native performance")
    roots = [
        h3.latlng_to_cell(a, b, 3)
        for a, b in ((12.97, 77.59), (0, 0), (45, 45), (-45, -45))
    ]
    cells = [c for root in roots for c in h3.cell_to_children(root, 8)[::67]]
    points = [h3.cell_to_latlng(c) for c in cells] * 10
    pairs = [address(c, 8) for c in cells] * 10
    backends: tuple[Backend, ...] = ("python", "auto")
    rates: dict[str, list[float]] = {"python": [], "auto": []}
    for repeat in range(7):
        for backend in backends if repeat % 2 else backends[::-1]:
            with Geocoder(pack, backend=backend) as geo:
                list(geo.reverse_columns(points[:1]))
                start = time.perf_counter()
                for _ in geo.reverse_columns(points):
                    pass
                rates[backend].append(len(points) / (time.perf_counter() - start))
    kernels = {}
    for backend in backends:
        _, kernel = select(backend)
        start = time.perf_counter_ns()
        for block, key in pairs:
            kernel(block, key)
        kernels[backend] = (time.perf_counter_ns() - start) / len(pairs)
    profile = cProfile.Profile()
    with Geocoder(pack, backend="python") as geo:
        profile.enable()
        for _ in geo.reverse_many(points):
            pass
        profile.disable()
    entries = profile.getstats()
    catalogue_seconds = next(
        entry.totaltime
        for entry in entries
        if isinstance(entry.code, CodeType)
        and entry.code.co_filename.endswith("/packs/catalogue.py")
        and entry.code.co_name == "record"
    )
    return {
        "python": measure(pack, "python"),
        "cython": measure(pack, "auto"),
        "paired_column_points": len(points),
        "paired_column_runs": rates,
        "median_column_rate_ratio": statistics.median(rates["auto"])
        / statistics.median(rates["python"]),
        "kernel_mean_ns": kernels,
        "public_profile_seconds": sum(entry.inlinetime for entry in entries),
        "catalogue_record_cumulative_seconds": catalogue_seconds,
        "limitations": [
            "Same synthetic pack and machine as the public reader benchmark.",
            "Seven alternating warm numeric-column runs; five catalogue places.",
            "Kernel only reconstructs stored H3 cells; "
            "it does not accelerate catalogue decoding.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = canonical(compare(args.pack)) + b"\n"
    args.output.write_bytes(report)
    print(report.decode(), end="")
