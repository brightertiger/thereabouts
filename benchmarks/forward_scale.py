"""Measure generated 7.8M interval and 90k spelling indexes."""

import argparse
import ipaddress
import json
import random
from typing import Any

from benchmarks.core_read_path import ROOT
from benchmarks.forward_queries import Query
from benchmarks.forward_workload import SEED, run


def spelling(value: int) -> str:
    suffix = ""
    for _ in range(4):
        suffix += chr(ord("a") + value % 26)
        value //= 26
    return f"Synthetic {suffix} town"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", choices=["before", "after"], default="after")
    args = parser.parse_args()
    root = ROOT / ".tmp/forward-scale"
    rng = random.Random(SEED)
    queries = []
    for _ in range(20000):
        version = rng.choice((4, 6))
        first_address = rng.randrange(3_900_000) * 2
        address = first_address if version == 4 else (0x2001 << 112) + first_address
        queries.append(Query(str(ipaddress.ip_address(address))))
    result: dict[str, Any] = {
        "scope": (
            "synthetic search scale, not a world compression estimate; "
            "7.8M single-address intervals, half v4/v6, each followed by a gap; "
            "one hot location dictionary; 90k distinct cities/names sharing common "
            "trigrams, 3 FST shards. Random IP exercises decoded-block cache misses."
        ),
        "intervals": 7_800_000,
        "name_keys": 90_000,
        "ip": run(root / "ip", "ip", queries, 20000),
        "ip_gap": run(root / "ip", "ip", [Query("0.0.0.1")], 20000),
        "names_exact": run(root / "names", "geocode", [Query(spelling(27182))], 20000),
        "names_random": run(
            root / "names", "geocode", [Query(spelling(i)) for i in range(90000)], 90000
        ),
        "names_fuzzy_common_grams": run(
            root / "names", "geocode", [Query("Synthetiq aaaa town")], 20
        ),
        "names_miss": run(root / "names", "geocode", [Query("Qzxvjkpqzxvjk")], 1000),
        "pack_bytes": {
            family: sum(p.stat().st_size for p in (root / family).iterdir())
            for family in ("ip", "names")
        },
    }
    for key in ("ip", "names_exact", "names_random"):
        assert set(result[key]["status_counts"]) == {"matched"}
    assert set(result["ip_gap"]["status_counts"]) == {"not_found"}
    path = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(path.read_text())
    series = data.setdefault("forward_scale", {})
    if "after" in series:
        series.setdefault("initial", series["after"])
    series[args.record] = result
    path.write_text(json.dumps(data, indent=2) + "\n")
    start, end = "<!-- forward-scale:start -->", "<!-- forward-scale:end -->"
    lines = [
        "| Synthetic workload | Median / p99 (µs) | Batch rows/s |",
        "| --- | ---: | ---: |",
    ]
    for key, value in result.items():
        if isinstance(value, dict) and "scalar_median_us" in value:
            lines.append(
                f"| {key} | {value['scalar_median_us']:.3f} / "
                f"{value['scalar_p99_us']:.3f} | "
                f"{value['batch_points_per_second']:,.0f} |"
            )
    section = start + "\n" + "\n".join(lines) + "\n" + end
    status = ROOT / "docs/CLIENT_STATUS.md"
    text = status.read_text()
    if start in text:
        text = text[: text.index(start)] + section + text[text.index(end) + len(end) :]
    else:
        text += "\n## Synthetic search scale\n\n" + section + "\n"
    status.write_text(text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
