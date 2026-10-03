"""Extract bounded IPv4/IPv6 sample ranges from the read-only golden dataset."""

import argparse
import ipaddress
import json
import tempfile
from pathlib import Path
from typing import Any

from thereabouts import _core
from tools.build_forward_samples import ROOT
from tools.forward_sample import COUNTRIES, Subset
from tools.source_fixture import write_source


def extract(source: Subset) -> list[dict[str, Any]]:
    selected: dict[tuple[str, int], int] = {}
    rows: list[dict[str, Any]] = []
    preferred = {
        4: int(ipaddress.ip_address("8.8.8.8")),
        6: int(ipaddress.ip_address("2001:4860:4860::8888")),
    }
    for table in source.inventory("ip_ranges"):
        for batch in source.batches(table):
            for row in batch.to_pylist():
                country, version = row["country_code"], row["ip_version"]
                key = (country, version)
                first = int.from_bytes(row["ip_start_packed"], "big")
                last = int.from_bytes(row["ip_end_packed"], "big")
                preferred_interval = first <= preferred[version] <= last
                if preferred_interval or (
                    country in COUNTRIES and selected.get(key, 0) < 512
                ):
                    rows.append(row)
                    selected[key] = selected.get(key, 0) + 1
            schema = batch.schema
        source.write("ip_ranges", rows, schema)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", prefix="ip-") as directory:
        source = Subset(args.golden, Path(directory))
        rows = extract(source)
        source.context(rows)
        total = sum(t["rows"] for t in source.inventory("ip_ranges"))
        provenance = source.finish("ip", total)
        provenance["countries"] = sorted({r["country_code"] for r in rows})
        provenance["subset_policy"] = (
            "first 512 intervals per country and IP version, plus intervals "
            "containing 8.8.8.8 and 2001:4860:4860::8888 regardless of country"
        )
        output = ROOT / "tests/fixtures/packs/ip-sample"
        _core.write_pack(
            str(source.output),
            "ip",
            str(output),
            {
                "data_version": "2026.10",
                "input_provenance": provenance,
                "sources": ["golden ip_ranges; DB-IP city lite"],
                "attribution": "DB-IP and golden context sources; see notices",
                "notices": {
                    name: (args.golden / name).read_text()
                    for name in ("DATA_LICENSES.md", "DATASET_CARD.md")
                },
            },
        )
        fields = (
            "source",
            "source_id",
            "ip_start",
            "ip_end",
            "ip_version",
            "country_code",
            "region",
            "city",
            "latitude",
            "longitude",
            "country_id",
            "state_id",
            "city_id",
        )
        oracle = {
            "provenance": provenance,
            "place_to_city": source.mappings,
            "rows": [{k: r.get(k) for k in fields} for r in rows],
        }
        write_source(ROOT / "tests/fixtures/ip-source.json.gz", oracle)
        print(
            json.dumps(
                {
                    "family": "ip",
                    "sample_rows": len(rows),
                    "world_source_rows": total,
                    "bytes": sum(p.stat().st_size for p in output.iterdir()),
                }
            )
        )


if __name__ == "__main__":
    main()
