"""Record intended result-contract vector changes against the pre-fix commit."""

import argparse
import json
import subprocess
from collections import Counter

from benchmarks.core_read_path import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", default="3d242a7")
    args = parser.parse_args()
    reports = {}
    for path in sorted((ROOT / "tests/fixtures").glob("*-vectors.json")):
        relative = path.relative_to(ROOT)
        original = subprocess.run(
            ["git", "show", f"{args.before}:{relative}"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        before = {c["id"]: c["result"] for c in json.loads(original.stdout)["cases"]}
        current = json.loads(path.read_text())["cases"]
        statuses = []
        changed = 0
        fields: Counter[str] = Counter()
        for case in current:
            old = before.get(case["id"])
            if old is None:
                continue
            new = case["result"]
            changed += old != new
            if old["status"] != new["status"]:
                statuses.append(
                    {"id": case["id"], "before": old["status"], "after": new["status"]}
                )
            fields.update(
                k for k in old.keys() | new.keys() if old.get(k) != new.get(k)
            )
        if fields:
            reports[path.name] = {
                "cases": len(current),
                "changed_cases": changed,
                "status_changes": statuses,
                "changed_fields": dict(fields),
            }
    path = ROOT / "docs/measurements/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(path.read_text())
    data["result_contract_rework"] = {
        "baseline_commit": args.before,
        "vectors": reports,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(data["result_contract_rework"], indent=2))


if __name__ == "__main__":
    main()
