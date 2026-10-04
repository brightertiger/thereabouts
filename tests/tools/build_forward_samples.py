"""Build small family packs from read-only golden inputs, inside this worktree."""

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from tests.tools.forward_sample import COUNTRIES, Subset
from tests.tools.source_fixture import write_source
from thereabouts import _core

ROOT = Path(__file__).resolve().parents[2]
# Thousands of rows exercise full compressed blocks, including cold evidence.
KEYS_PER_COUNTRY = {"postal": 1024, "airports": 512, "locode": 512}
PREFERRED = {
    "postal": {
        "BE": {"1000"},
        "NL": {"1012AB"},
        "LU": {"1111"},
        "FR": {"75001"},
        "TR": {"34400"},
        "IN": {"110001", "400001"},
        "US": {"62701"},
    },
}


def postal(source: Subset) -> list[dict[str, Any]]:
    chosen: dict[str, set[str]] = {country: set() for country in COUNTRIES}
    rows: list[dict[str, Any]] = []
    for table in source.inventory("postal_codes"):
        for batch in source.batches(table):
            for row in batch.to_pylist():
                country = row["country_code"]
                if country not in COUNTRIES:
                    continue
                code = row["postal_code"].strip().upper().replace(" ", "")
                if (
                    len(chosen[country]) < KEYS_PER_COUNTRY["postal"]
                    or code in PREFERRED["postal"][country]
                ):
                    chosen[country].add(code)
                if code in chosen[country]:
                    rows.append(row)
            schema = batch.schema
        source.write("postal_codes", rows, schema)
    return rows


def points(source: Subset, family: str) -> list[dict[str, Any]]:
    chosen: dict[str, set[str]] = {c: set() for c in COUNTRIES}
    rows: list[dict[str, Any]] = []
    preferred = {"CDG", "AMS", "BRU", "LUX", "IST", "BOM", "DEL", "SPI"}
    primary = "airports" if family == "airports" else "trade_locations"
    field = "ident" if family == "airports" else "locode"
    for table in source.inventory(primary):
        for batch in source.batches(table):
            for row in batch.to_pylist():
                country = row["country_code"]
                if country not in COUNTRIES:
                    continue
                code = row[field]
                if (
                    len(chosen[country]) < KEYS_PER_COUNTRY[family]
                    or row["iata_code"] in preferred
                    or (family == "locode" and code == "INBOM")
                ):
                    chosen[country].add(code)
                if code in chosen[country]:
                    rows.append(row)
            schema = batch.schema
        source.write(primary, rows, schema)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument(
        "--family", choices=["postal", "airports", "locode"], required=True
    )
    args = parser.parse_args()
    output = ROOT / f"tests/fixtures/packs/{args.family}-sample"
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", prefix="forward-") as directory:
        source = Subset(args.golden, Path(directory))
        rows = (
            postal(source) if args.family == "postal" else points(source, args.family)
        )
        source.context(rows)
        primary = {
            "postal": "postal_codes",
            "airports": "airports",
            "locode": "trade_locations",
        }[args.family]
        total = sum(t["rows"] for t in source.inventory(primary))
        provenance = source.finish(args.family, total)
        provenance["subset_policy"] = (
            f"first {KEYS_PER_COUNTRY[args.family]} distinct codes per country "
            "plus named examples; "
            "all observations for selected keys and referenced geographic context"
        )
        _core.write_pack(
            str(source.output),
            args.family,
            str(output),
            {
                "core_pack": str(ROOT / "tests/fixtures/packs/core-sample"),
                "data_version": "2026.10",
                "input_provenance": provenance,
                "sources": ["golden dataset; original digests retained"],
                "attribution": "GeoNames and golden context sources; see notices",
                "notices": {
                    name: (args.golden / name).read_text()
                    for name in ("DATA_LICENSES.md", "DATASET_CARD.md")
                },
            },
        )
        # Independent source rows are committed alongside the API snapshots.
        oracle = {
            "provenance": provenance,
            "place_to_city": source.mappings,
            "rows": [
                {
                    k: r.get(k)
                    for k in (
                        "country_code",
                        "postal_code",
                        "locode",
                        "location",
                        "name_ascii",
                        "ident",
                        "iata_code",
                        "icao_code",
                        "gps_code",
                        "local_code",
                        "name",
                        "place_name",
                        "latitude",
                        "longitude",
                        "country_id",
                        "state_id",
                        "city_id",
                        "source",
                        "source_id",
                    )
                }
                for r in rows
            ],
        }
        write_source(ROOT / f"tests/fixtures/{args.family}-source.json.gz", oracle)
    print(
        json.dumps(
            {
                "family": args.family,
                "sample_rows": len(rows),
                "world_source_rows": total,
                "bytes": sum(p.stat().st_size for p in output.iterdir()),
            }
        )
    )


if __name__ == "__main__":
    main()
