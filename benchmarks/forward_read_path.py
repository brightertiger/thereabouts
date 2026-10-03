"""Measure forward scalar/batch speed and estimate sizes by sample ratio."""

import argparse
import json
import platform
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from benchmarks.core_read_path import ROOT
from thereabouts import Geocoder


def measure(family: str, iterations: int) -> dict[str, Any]:
    pack = ROOT / f"tests/fixtures/packs/{family}-sample"
    bundle = json.loads((ROOT / f"tests/fixtures/{family}-vectors.json").read_text())
    cases = [c for c in bundle["cases"] if c["result"]["status"] == "matched"]
    country = "US"
    queries = [
        c["request"]["values"][0]
        for c in cases
        if c["request"].get("country") == country
    ]
    if not queries:
        raise ValueError("Benchmark needs matching US vectors")
    values = [queries[i % len(queries)] for i in range(iterations)]
    durations, rates = [], []
    verb = "airport" if family == "airports" else family
    kwargs: dict[str, Any] = {"country": country}
    if family == "airports":
        kwargs["scheme"] = "ident"
    with Geocoder(pack) as geo:
        scalar = getattr(geo, verb)
        batch = getattr(geo, verb + "_columns")
        for value in queries:
            scalar(value, **kwargs)
        for value in values:
            start = time.perf_counter_ns()
            scalar(value, **kwargs)
            durations.append(time.perf_counter_ns() - start)
        for _ in range(7):
            start_batch = time.perf_counter()
            result = batch(values, **kwargs)
            elapsed = time.perf_counter() - start_batch
            assert len(result["status"]) == iterations
            rates.append(iterations / elapsed)
    manifest = json.loads((pack / "manifest.json").read_text())
    source = json.loads((ROOT / f"tests/fixtures/{family}-source.json").read_text())
    size = sum(p.stat().st_size for p in pack.iterdir())
    world_rows = manifest["inputs"]["options"]["input_provenance"]["world_source_rows"]
    return {
        "pack_bytes": size,
        "sample_rows": len(source["rows"]),
        "world_source_rows": world_rows,
        "estimated_world_bytes": round(size * world_rows / len(source["rows"])),
        "estimate_method": (
            "linear sample byte/row ratio including sample fixed overhead; "
            "not a world measurement"
        ),
        "vectors": len(bundle["cases"]),
        "iterations": iterations,
        "distinct_queries": len(queries),
        "country": country,
        "scalar_median_us": statistics.median(durations) / 1000,
        "scalar_p99_us": float(np.percentile(durations, 99)) / 1000,
        "batch_points_per_second": statistics.median(rates),
        "batch_repeats": rates,
    }


def update_status(data: dict[str, Any]) -> None:
    """Keep the documented measurement table derived from this script's output."""
    path = ROOT / "docs/CLIENT_STATUS.md"
    start, end = (
        "<!-- forward-measurements:start -->",
        "<!-- forward-measurements:end -->",
    )
    rows = [
        (
            "| Family | Sample bytes / rows | Real vectors | Scalar median / p99 (µs) "
            "| Batch rows/s | Estimated world bytes |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family, value in data["families"].items():
        rows.append(
            f"| {family} | {value['pack_bytes']:,} / {value['sample_rows']:,} | "
            f"{value['vectors']} | {value['scalar_median_us']:.3f} / "
            f"{value['scalar_p99_us']:.3f} | {value['batch_points_per_second']:,.0f} | "
            f"{value['estimated_world_bytes']:,} |"
        )
    text = path.read_text()
    if start in text:
        a, b = text.index(start), text.index(end) + len(end)
        text = text[:a] + start + "\n" + "\n".join(rows) + "\n" + end + text[b:]
    else:
        text += (
            "\n## Forward measurements\n\n"
            + start
            + "\n"
            + "\n".join(rows)
            + "\n"
            + end
            + "\n"
        )
    path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family", choices=["postal", "airports"])
    parser.add_argument("--iterations", type=int, default=20000)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/CLIENT_FORWARD_MEASUREMENTS.json"
    )
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error("at least 100 iterations are required")
    existing = (
        json.loads(args.output.read_text())
        if args.output.exists()
        else {
            "machine": json.loads(
                (ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json").read_text()
            )["machine"],
            "families": {},
        }
    )
    existing["machine"] = {
        "chip": subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"], text=True
        ).strip()
        if platform.system() == "Darwin"
        else platform.machine(),
        "memory_bytes": int(
            subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
        )
        if platform.system() == "Darwin"
        else None,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    existing["families"][args.family] = measure(args.family, args.iterations)
    args.output.write_text(json.dumps(existing, indent=2) + "\n")
    update_status(existing)
    print(json.dumps(existing["families"][args.family], indent=2))


if __name__ == "__main__":
    main()
