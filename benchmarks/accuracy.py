"""Compare the shipped table with original-point labels, never centre labels."""

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from build_data.reference.oracle import Reference
from build_data.sources import sha256
from thereabouts import Geocoder

from .sampling import sample


def measure(
    data: Path,
    reference_path: Path,
    count: int,
    seed: int,
    points_output: Path | None = None,
) -> dict[str, Any]:
    reference = Reference(reference_path)
    result: dict[str, Any] = {
        "count_per_workload": count,
        "seed": seed,
        "nearby_radius_km": 5,
        "nearby_selection": (
            "uniform settlement, uniform-area spherical disk; "
            "reject outside reference land"
        ),
    }
    try:
        with Geocoder(data) as geocoder:
            result["snapshot_id"] = geocoder.info()["snapshot_id"]
            result["resolution"] = geocoder.info()["resolution"]
            result["manifest_sha256"] = sha256(data / "manifest.json")
            result["reference_manifest_sha256"] = sha256(
                reference_path / "manifest.json"
            )
            for nearby, name in (
                (False, "area_uniform_land"),
                (True, "settlement_nearby_land"),
            ):
                coordinates = sample(
                    reference, count, seed + int(nearby), nearby=nearby
                )
                if not nearby and points_output is not None:
                    points_output.parent.mkdir(parents=True, exist_ok=True)
                    np.save(points_output, coordinates, allow_pickle=False)
                mismatches = {field: 0 for field in ("country", "state", "city")}
                no_row = 0
                for start in range(0, count, 4096):
                    points = coordinates[start : start + 4096]
                    expected = reference.locations(reference.labels(points))
                    actual = geocoder.reverse_many(map(tuple, points))
                    for truth, answer in zip(expected, actual, strict=True):
                        no_row += answer is None
                        for field in mismatches:
                            mismatches[field] += getattr(truth, field, None) != getattr(
                                answer, field, None
                            )
                result[name] = {
                    "mismatch_counts": mismatches,
                    "mismatch_percent": {
                        field: value * 100 / count
                        for field, value in mismatches.items()
                    },
                    "no_row_count": no_row,
                }
    finally:
        reference.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/h3-world"))
    parser.add_argument("--reference", type=Path, default=Path("data/reference"))
    parser.add_argument("--count", type=int, default=100000)
    parser.add_argument("--seed", type=int, default=20261001)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/accuracy.json"))
    parser.add_argument(
        "--points-output", type=Path, default=Path("data/benchmarks/points.npy")
    )
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("count must be positive")
    result = measure(
        args.data, args.reference, args.count, args.seed, args.points_output
    )
    text = json.dumps(result, indent=2) + "\n"
    args.output.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
