"""Extract phone prefixes and metadata from the read-only golden dataset."""

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from thereabouts import _core
from tools.build_forward_samples import ROOT
from tools.forward_sample import COUNTRIES, Subset


def extract(source: Subset) -> list[dict[str, Any]]:
    chosen: dict[str, set[str]] = {c: set() for c in COUNTRIES}
    rows: list[dict[str, Any]] = []
    for kind in ("phone_prefixes", "phone_metadata"):
        for table in source.inventory(kind):
            selected = []
            for batch in source.batches(table):
                for row in batch.to_pylist():
                    codes = (
                        row["country_codes"]
                        if kind == "phone_prefixes"
                        else [row["territory"]]
                    )
                    if not codes or not set(codes) <= COUNTRIES:
                        continue
                    prefix = row.get("prefix") or row["calling_code"]
                    if kind == "phone_prefixes":
                        for country in codes:
                            if (
                                len(chosen[country]) < 32
                                or prefix.startswith("9122")
                                or prefix
                                in {
                                    "9122",
                                    "9111",
                                    "1202",
                                    "33",
                                    "32",
                                    "31",
                                    "352",
                                    "90",
                                }
                            ):
                                chosen[country].add(prefix)
                        if not any(prefix in chosen[c] for c in codes):
                            continue
                    selected.append(row)
                    rows.append(row | {"table": kind, "country_codes": codes})
                schema = batch.schema
            # Supply even empty partitions; the manifest explicitly includes both kinds.
            source.write(kind, selected, schema)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", prefix="phone-") as directory:
        source = Subset(args.golden, Path(directory))
        rows = extract(source)
        context = []
        for row in rows:
            for code in row["country_codes"]:
                context.append({"country_code": code, "country_id": "country:" + code})
            for place in row.get("place_ids") or []:
                context.append(
                    {
                        "country_code": row["country_codes"][0],
                        "country_id": row.get("country_id"),
                        "city_id": place,
                    }
                )
        source.context(context)
        total = sum(
            t["rows"]
            for kind in ("phone_prefixes", "phone_metadata")
            for t in source.inventory(kind)
        )
        provenance = source.finish("phone", total)
        provenance["subset_policy"] = (
            "first 32 distinct prefixes per country, named prefixes, "
            "all observations of selected prefixes, including published 91222-91227 "
            "Mumbai prefixes (no literal 9122 row); metadata for the seven countries"
        )
        output = ROOT / "tests/fixtures/packs/phone-sample"
        _core.write_pack(
            str(source.output),
            "phone",
            str(output),
            {
                "data_version": "2026.10",
                "input_provenance": provenance,
                "sources": ["golden phone prefix and metadata tables"],
                "attribution": "libphonenumber and golden context sources; see notices",
                "notices": {
                    name: (args.golden / name).read_text()
                    for name in ("DATA_LICENSES.md", "DATASET_CARD.md")
                },
            },
        )
        fields = (
            "table",
            "prefix",
            "calling_code",
            "territory",
            "country_codes",
            "country_id",
            "place_id",
            "place_ids",
            "language",
            "description",
            "source",
            "source_id",
            "link_status",
            "link_method",
        )
        (ROOT / "tests/fixtures/phone-source.json").write_text(
            json.dumps(
                {
                    "provenance": provenance,
                    "rows": [{k: r.get(k) for k in fields} for r in rows],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        print(
            json.dumps(
                {
                    "family": "phone",
                    "sample_rows": len(rows),
                    "world_source_rows": total,
                    "bytes": sum(p.stat().st_size for p in output.iterdir()),
                }
            )
        )


if __name__ == "__main__":
    main()
