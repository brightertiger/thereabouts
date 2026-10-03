"""Measure forward scalar/batch speed and estimate sizes by sample ratio."""

import argparse
import json
import platform
import subprocess
from pathlib import Path
from typing import Any

from benchmarks.core_read_path import ROOT
from benchmarks.forward_queries import Query, airport_defaults, misses, queries
from benchmarks.forward_sizes import estimate
from benchmarks.forward_workload import run
from thereabouts import Geocoder
from tools.source_fixture import read_source


def measure(family: str, iterations: int) -> dict[str, Any]:
    pack_name = "core-names" if family == "geocode" else family
    pack = ROOT / f"tests/fixtures/packs/{pack_name}-sample"
    bundle = json.loads((ROOT / f"tests/fixtures/{family}-vectors.json").read_text())
    population = queries(family)
    verb = {"airports": "airport", "plates": "plate"}.get(family, family)
    absent = misses(family)
    with Geocoder(pack) as geo:
        scalar = getattr(geo, verb)
        assert all(scalar(q.value, **q.kwargs()).status == "not_found" for q in absent)
        hot = next(
            q for q in population if scalar(q.value, **q.kwargs()).status == "matched"
        )
    workloads = {
        "hot": run(pack, verb, [hot], iterations),
        "random": run(pack, verb, population, iterations),
        "miss": run(pack, verb, absent, iterations),
    }
    if family == "airports":
        workloads["default_scheme"] = run(pack, verb, airport_defaults(), iterations)
    if family == "geocode":
        workloads["fuzzy"] = run(
            pack, verb, [Query("Utrechx", (("country", "NL"),))], 1000
        )
    countries = sorted({v for q in population for k, v in q.options if k == "country"})
    manifest = json.loads((pack / "manifest.json").read_text())
    source = read_source(ROOT / f"tests/fixtures/{family}-source.json.gz")
    size = sum(p.stat().st_size for p in pack.iterdir())
    world_rows = manifest["inputs"]["options"]["input_provenance"]["world_source_rows"]
    return {
        "pack_bytes": size,
        "sample_rows": len(source["rows"]),
        "world_source_rows": world_rows,
        **estimate(pack, world_rows, len(source["rows"])),
        "estimate_scope": (
            "city-name index and supporting catalogue only; excludes spatial core"
            if family == "geocode"
            else "family pack including supporting catalogue"
        ),
        "vectors": len(bundle["cases"]),
        "workload_scope": "all source keys; plates use code/country assertions",
        "countries": countries,
        "workloads": workloads,
        **workloads["hot"],
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
            "| Random median / p99 (µs) | Random batch rows/s | Estimated world bytes |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family, value in data["families"].items():
        random = value.get("workloads", {}).get("random", value)
        rows.append(
            f"| {family} | {value['pack_bytes']:,} / {value['sample_rows']:,} | "
            f"{value['vectors']} | {value['scalar_median_us']:.3f} / "
            f"{value['scalar_p99_us']:.3f} | "
            f"{random['scalar_median_us']:.3f} / "
            f"{random['scalar_p99_us']:.3f} | "
            f"{random['batch_points_per_second']:,.0f} | "
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
    parser.add_argument(
        "family",
        choices=["postal", "airports", "locode", "phone", "ip", "plates", "geocode"],
    )
    parser.add_argument("--iterations", type=int, default=20000)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/CLIENT_FORWARD_MEASUREMENTS.json"
    )
    parser.add_argument("--record", choices=["before", "after"], default="after")
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
    measurement = measure(args.family, args.iterations)
    existing.setdefault("history", {}).setdefault(args.family, {})[args.record] = (
        measurement
    )
    existing["families"][args.family] = measurement
    core_path = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    core = json.loads(core_path.read_text())
    core.setdefault("forward_workloads", {}).setdefault(args.family, {})[
        args.record
    ] = measurement
    core_path.write_text(json.dumps(core, indent=2) + "\n")
    packs = {
        pack.name: sum(p.stat().st_size for p in pack.rglob("*") if p.is_file())
        for pack in sorted((ROOT / "tests/fixtures/packs").iterdir())
        if pack.is_dir() and pack.name not in {"core-sample", "core-synthetic"}
    }
    extracts = sum(
        p.stat().st_size for p in (ROOT / "tests/fixtures").glob("*-source.json.gz")
    )
    vectors = sum(
        p.stat().st_size
        for p in (ROOT / "tests/fixtures").glob("*-vectors.json")
        if not p.name.startswith("core-")
    )
    existing["fixture_packs"] = {
        "bytes_by_pack": packs,
        "total_bytes": sum(packs.values()),
        "source_extract_bytes": extracts,
        "shared_vector_bytes": vectors,
        "packs_extracts_vectors_bytes": sum(packs.values()) + extracts + vectors,
    }
    args.output.write_text(json.dumps(existing, indent=2) + "\n")
    update_status(existing)
    print(json.dumps(existing["families"][args.family], indent=2))
    print(json.dumps(existing["fixture_packs"], indent=2))


if __name__ == "__main__":
    main()
