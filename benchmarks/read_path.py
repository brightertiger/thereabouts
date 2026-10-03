"""Profile the public API against a populated synthetic pack (no source downloads)."""

import argparse
import cProfile
import io
import json
import platform
import pstats
import resource
import statistics
import time
from pathlib import Path

import numpy as np

from thereabouts.client import Geocoder
from thereabouts.reading.backend import Backend


def profile(geo: Geocoder, points: list[tuple[float, float]], columns: bool) -> str:
    profiler = cProfile.Profile()
    profiler.enable()
    if columns:
        for _ in geo.reverse_columns(points):
            pass
    else:
        for point in points:
            geo.reverse(*point)
    profiler.disable()
    output = io.StringIO()
    pstats.Stats(profiler, stream=output).strip_dirs().sort_stats(
        "cumtime"
    ).print_stats(25)
    return output.getvalue()


def measure(root: Path, backend: Backend) -> dict[str, object]:
    pack = root / "pack"
    opened = time.perf_counter_ns()
    geo = Geocoder(pack, backend=backend)
    open_ns = time.perf_counter_ns() - opened
    first_point = np.load(root / "shuffled.npy")[0]
    started = time.perf_counter_ns()
    geo.reverse(float(first_point[0]), float(first_point[1]))
    first_ns = time.perf_counter_ns() - started
    with geo:
        results: dict[str, object] = {}
        for order in ("clustered", "shuffled"):
            points = [tuple(map(float, row)) for row in np.load(root / f"{order}.npy")]
            pairs = [(row[0], row[1]) for row in points]
            # Populate the lazy catalogue using the full spread before warm timing.
            started = time.perf_counter_ns()
            for point in pairs:
                geo.reverse(*point)
            warmup_ns = time.perf_counter_ns() - started
            scalar = []
            for point in pairs[:10000]:
                start: float = time.perf_counter_ns()
                geo.reverse(*point)
                scalar.append(time.perf_counter_ns() - start)
            column_times, object_times = [], []
            for _ in range(5):
                start = time.perf_counter()
                for _ in geo.reverse_columns(pairs):
                    pass
                column_times.append(time.perf_counter() - start)
                start = time.perf_counter()
                for _ in geo.reverse_many(pairs[:10000]):
                    pass
                object_times.append(time.perf_counter() - start)
            results[order] = {
                "points": len(pairs),
                "catalogue_warmup_ns": warmup_ns,
                "scalar_median_ns": statistics.median(scalar),
                "scalar_p99_ns": sorted(scalar)[int(len(scalar) * 0.99)],
                "columns_per_second": len(pairs) / statistics.median(column_times),
                "objects_per_second": 10000 / statistics.median(object_times),
                "column_seconds": column_times,
                "object_seconds": object_times,
                "scalar_profile": profile(geo, pairs[:5000], False),
                "column_profile": profile(geo, pairs, True),
            }
        return {
            "open_ns": open_ns,
            "first_lookup_ns": first_ns,
            "machine": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "info": geo.info(),
            "installed_bytes": sum(
                p.stat().st_size for p in pack.rglob("*") if p.is_file()
            ),
            "peak_process_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss,
            "workloads": results,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--backend", choices=("python", "auto"), default="auto")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(measure(args.sample, args.backend), indent=2) + "\n"
    )
