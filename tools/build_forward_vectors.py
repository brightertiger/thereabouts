"""Freeze shared forward snapshots after asserting the original legacy cases."""

import argparse
import json
from pathlib import Path
from typing import Any

from tests.conformance.forward_legacy import assert_case, resolve
from thereabouts import Geocoder

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def write(path: Path, pack: str, cases: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "thereabouts-conformance-2",
                "pack": pack,
                "cases": cases,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("family", choices=["postal"])
    family = parser.parse_args().family
    source = json.loads((FIXTURES / f"{family}-source.json").read_text())
    requests = []
    codes: dict[str, set[str]] = {}
    for row in source["rows"]:
        country, code = row["country_code"], row["postal_code"]
        chosen = codes.setdefault(country, set())
        if code not in chosen and len(chosen) < 3:
            chosen.add(code)
            requests.append({"kind": family, "values": [code], "country": country})
    first = requests[0]
    requests += [
        first
        | {
            "values": [" " + first["values"][0].lower() + " "],
            "country": first["country"].lower(),
        },
        {"kind": family, "values": ["75001"]},
        {"kind": family, "values": [""], "country": "FR"},
        {"kind": family, "values": ["x\u0000y"], "country": "FR"},
        {"kind": family, "values": [1000], "country": "BE"},
        {"kind": family, "values": ["not-a-code"], "country": "FR"},
        {"kind": family, "values": ["1000"], "country": "BEL"},
    ]
    with Geocoder(FIXTURES / f"packs/{family}-sample") as geo:
        cases = [
            {
                "id": f"{family}-{i:03}",
                "request": r,
                "result": resolve(geo, r).to_dict(),
            }
            for i, r in enumerate(requests)
        ]
    assert len(cases) >= 20
    write(FIXTURES / f"{family}-vectors.json", f"packs/{family}-sample", cases)
    with Geocoder(FIXTURES / f"packs/{family}-synthetic") as geo:
        cases = []
        for case in json.loads((FIXTURES / "conformance.json").read_text())["cases"]:
            if case["request"]["kind"] != family:
                continue
            assert_case(geo, case)
            cases.append(
                {
                    "id": f"legacy-{case['id']}",
                    "request": case["request"],
                    "result": resolve(geo, case["request"]).to_dict(),
                }
            )
    write(
        FIXTURES / f"{family}-synthetic-vectors.json",
        f"packs/{family}-synthetic",
        cases,
    )
    print(f"Frozen {family} vectors; {len(cases)} legacy cases independently asserted")


if __name__ == "__main__":
    main()
