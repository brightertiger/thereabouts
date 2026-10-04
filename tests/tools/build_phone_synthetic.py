"""Build explicit shared-code, nested-prefix and linked-city phone fixtures."""

import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from tests.tools.build_sample_pack import sha
from thereabouts import _core

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    source = ROOT / "tests/fixtures/datasets/forward-synthetic"
    # The existing fixture builder records its manifest below golden/.
    manifests = list(source.rglob("manifest.json"))
    manifest_path = next(
        p
        for p in manifests
        if json.loads(p.read_text()).get("schema_version") == "golden-2"
    )
    manifest = json.loads(manifest_path.read_text())
    base = manifest_path.parent / manifest["data_root"]
    output = ROOT / "tests/fixtures/datasets/phone-synthetic"
    tables = []
    for table in manifest["tables"]:
        if table["kind"] not in {
            "places",
            "countries",
            "subdivisions",
            "canonical_cities",
            "place_to_city",
        }:
            continue
        destination = output / table["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(base / table["path"], destination)
        tables.append(table)
    schema = pa.schema(
        [
            ("source", pa.string()),
            ("source_id", pa.string()),
            ("prefix", pa.string()),
            ("calling_code", pa.string()),
            ("territory", pa.string()),
            ("country_codes", pa.list_(pa.string())),
            ("country_id", pa.string()),
            ("place_id", pa.string()),
            ("place_ids", pa.list_(pa.string())),
            ("description", pa.string()),
        ]
    )
    for kind, values in [
        (
            "phone_prefixes",
            [("1202", "AA", "city:synthetic:A"), ("120", "BB", "country:BB")],
        ),
        ("phone_metadata", [("1", "AA", "country:AA"), ("1", "BB", "country:BB")]),
    ]:
        rows = [
            {
                "source": "synthetic",
                "source_id": str(i),
                "prefix": prefix,
                "calling_code": "1",
                "territory": country,
                "country_codes": [country],
                "country_id": "country:" + country,
                "place_id": place,
                "place_ids": [place],
                "description": "Published linked prefix",
            }
            for i, (prefix, country, place) in enumerate(values)
        ]
        path = output / f"{kind}.parquet"
        pq.write_table(
            pa.Table.from_pylist(rows, schema=schema), path, compression="zstd"
        )
        tables.append(
            {
                "kind": kind,
                "path": path.name,
                "rows": len(rows),
                "size": path.stat().st_size,
                "sha256": sha(path),
            }
        )
    manifest = {
        "schema_version": "golden-2",
        "completed": True,
        "data_root": ".",
        "tables": tables,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    _core.write_pack(
        str(output),
        "phone",
        str(ROOT / "tests/fixtures/packs/phone-synthetic"),
        {
            "core_pack": str(ROOT / "tests/fixtures/packs/core-synthetic"),
            "data_version": "synthetic",
            "sources": ["synthetic phone cases"],
            "attribution": "Synthetic fixture; public domain",
            "notices": {"LICENSE": "Public domain"},
        },
    )


if __name__ == "__main__":
    main()
