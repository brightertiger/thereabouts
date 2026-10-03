"""Build a names-focused core sample from canonical cities in the read-only dataset."""

import argparse
import json
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import pyarrow as pa

from thereabouts import _core
from tools.build_forward_samples import ROOT
from tools.forward_sample import COUNTRIES, Subset


def key(value: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(c)
    ).replace("-", " ")


def choose(source: Subset) -> tuple[list[dict[str, Any]], pa.Schema]:
    top: dict[str, list[dict[str, Any]]] = {c: [] for c in COUNTRIES}
    named: dict[str, dict[str, Any]] = {}
    examples = {
        "paris",
        "lyon",
        "saint etienne",
        "liege",
        "bruxelles",
        "brussels",
        "amsterdam",
        "luxembourg",
        "istanbul",
        "mumbai",
        "delhi",
        "new delhi",
        "new york",
        "springfield",
        "kidarakulam",
        "karakulam",
    }
    for table in source.inventory("canonical_cities"):
        if table.get("country") not in COUNTRIES:
            continue
        for batch in source.batches(table):
            schema = batch.schema
            for row in batch.to_pylist():
                country = row["country_code"]
                if country not in COUNTRIES:
                    continue
                top[country].append(row)
                top[country].sort(key=lambda r: (-(r["population"] or 0), r["city_id"]))
                del top[country][12:]
                if any(
                    key(row.get(field) or "") in examples
                    for field in ("name", "name_en")
                ):
                    named[row["city_id"]] = row
    for rows in top.values():
        named.update((r["city_id"], r) for r in rows)
    return [named[k] for k in sorted(named)], schema


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", prefix="names-") as directory:
        source = Subset(args.golden, Path(directory))
        rows, schema = choose(source)
        source.context(
            [r | {"country_id": "country:" + r["country_code"]} for r in rows]
        )
        source.tables = [t for t in source.tables if t["kind"] != "canonical_cities"]
        source.write("canonical_cities", rows, schema)
        total = sum(t["rows"] for t in source.inventory("canonical_cities"))
        provenance = source.finish("core", total)
        provenance["subset_policy"] = (
            "twelve most populous canonical cities per country plus named examples "
            "and all canonical Springfields in the seven countries; "
            "Kidarakulam/Karakulam supplies a real differing English spelling"
        )
        manifest_path = source.output / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["normalization"] = source.manifest["normalization"]
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n")
        output = ROOT / "tests/fixtures/packs/core-names-sample"
        _core.write_pack(
            str(source.output),
            "core",
            str(output),
            {
                "data_version": "2026.10",
                "input_provenance": provenance,
                "allow_missing_tables": ["cells", "timezone_cells", "zone_tables"],
                "sources": ["golden canonical_cities and geography"],
                "attribution": "GeoNames and golden context sources; see notices",
                "notices": {
                    name: (args.golden / name).read_text()
                    for name in ("DATA_LICENSES.md", "DATASET_CARD.md")
                },
            },
        )
        fields = (
            "city_id",
            "name",
            "name_en",
            "kind",
            "population",
            "latitude",
            "longitude",
            "country_code",
        )
        (ROOT / "tests/fixtures/geocode-source.json").write_text(
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
                    "family": "geocode",
                    "pack_family": "core",
                    "sample_rows": len(rows),
                    "world_source_rows": total,
                    "bytes": sum(p.stat().st_size for p in output.iterdir()),
                }
            )
        )


if __name__ == "__main__":
    main()
