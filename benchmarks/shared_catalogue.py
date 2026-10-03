"""Record fixture sizes and intentional vector changes for the shared catalogue."""

import argparse
import json
import subprocess
from typing import Any

from benchmarks.core_read_path import ROOT
from benchmarks.forward_sizes import FAMILIES, estimate, measure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="07fbae7")
    args = parser.parse_args()
    values: dict[str, Any] = {}
    for family in FAMILIES:
        pack = ROOT / f"tests/fixtures/packs/{family}-sample"
        info = json.loads((pack / "manifest.json").read_text())
        value = measure(pack)
        world = info["inputs"]["options"]["input_provenance"]["world_source_rows"]
        value.update(estimate(pack, world, value["source_rows"]))
        value["catalogue_bytes"] = info["storage"]["catalogue_bytes"]
        name = f"tests/fixtures/{family}-vectors.json"
        old = json.loads(
            subprocess.check_output(["git", "show", f"{args.before}:{name}"], cwd=ROOT)
        )
        current = json.loads((ROOT / name).read_text())
        previous = {c["id"]: c for c in old["cases"]}
        assert len(previous) == len(current["cases"])
        changed = []
        timezone_results = 0
        for case in current["cases"]:
            prior = previous[case["id"]]
            assert prior["request"] == case["request"]
            if prior["result"] != case["result"]:
                changed.append(case["id"])
            result = case["result"]
            timezone_results += sum(
                r["timezone"] is not None for r in (result["candidates"] or [result])
            )
        value.update(
            changed_vector_ids=changed,
            vectors=len(previous),
            results_with_timezone=timezone_results,
        )
        values[family] = value
    path = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(path.read_text())
    baseline = json.loads(
        subprocess.check_output(
            ["git", "show", f"{args.before}:docs/CLIENT_CORE_MEASUREMENTS.json"],
            cwd=ROOT,
        )
    )
    data["format_followups_baseline"] = {
        "commit": args.before,
        "multishard": baseline["catalogue_read_rework"]["after"],
        "core_open_seconds": baseline["open_seconds"],
        "core_open_rss_delta_bytes": baseline["open_rss_delta_bytes"],
    }
    data["shared_catalogue"] = {
        "baseline_commit": args.before,
        "families": values,
        "core_sample_bytes": sum(
            p.stat().st_size
            for p in (ROOT / "tests/fixtures/packs/core-sample").iterdir()
        ),
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data["shared_catalogue"], indent=2))


if __name__ == "__main__":
    main()
