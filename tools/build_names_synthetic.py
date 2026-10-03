"""Explicit English and alternate spellings, independent of legacy reverse fixtures."""

import json
import shutil

import pyarrow as pa
import pyarrow.parquet as pq

from thereabouts import _core
from tools.build_sample_pack import ROOT, sha


def main() -> None:
    original = ROOT / "tests/fixtures/datasets/core-synthetic/golden"
    output = ROOT / "tests/fixtures/datasets/names-synthetic"
    manifest = json.loads((original / "manifest.json").read_text())
    for table in manifest["tables"]:
        source = original / manifest["data_root"] / table["path"]
        destination = output / table["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if table["kind"] == "canonical_cities":
            data = pq.read_table(source)
            rows = data.to_pylist()
            for row in rows:
                if row["city_id"] == "city:synthetic:A":
                    row["name_en"] = "Munich Tokyo"
            pq.write_table(
                pa.Table.from_pylist(rows, schema=data.schema),
                destination,
                compression="zstd",
            )
            table["sha256"] = sha(destination)
            table["size"] = destination.stat().st_size
        else:
            shutil.copyfile(source, destination)
    aliases = output / "names.parquet"
    rows = [
        {
            "city_id": "city:synthetic:A",
            "name": "Minga Tokyo",
            "kind": "alternate",
            "language": "bar",
        }
    ]
    pq.write_table(pa.Table.from_pylist(rows), aliases, compression="zstd")
    manifest["tables"].append(
        {
            "kind": "names",
            "path": aliases.name,
            "rows": len(rows),
            "sha256": sha(aliases),
            "size": aliases.stat().st_size,
        }
    )
    manifest["data_root"] = "."
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    _core.write_pack(
        str(output),
        "core",
        str(ROOT / "tests/fixtures/packs/core-names-synthetic"),
        {
            "data_version": "synthetic",
            "sources": ["explicit synthetic name spellings"],
            "attribution": "Synthetic fixture; public domain",
            "notices": {"LICENSE": "Public domain"},
        },
    )


if __name__ == "__main__":
    main()
