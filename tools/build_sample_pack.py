"""Reproducibly subset read-only golden data and export a core sample.

Run: uv run python -m tools.build_sample_pack --golden /path/to/data/golden.
Benelux rows are taken from all r3 blocks intersecting a conservatively buffered
continental bounding box. Six additional complete r3 blocks cover Paris,
Istanbul, Mumbai, Delhi, Springfield (Illinois) and a distant-nearest Montana
block. Only catalogue reference
closure is retained. Overlapping timezone cells are retained, never resolved.
The original inventory digest, every consumed file digest, subset definition and
explicit dataset version are recorded in the output manifest.
"""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import h3
import pyarrow as pa
import pyarrow.parquet as pq

from thereabouts import _core
from tools.sample_evidence import extract

ROOT = Path(__file__).resolve().parents[1]
CENTRES = {
    "Paris": (48.8566, 2.3522),
    "Istanbul": (41.0082, 28.9784),
    "Mumbai": (19.0760, 72.8777),
    "Delhi": (28.6139, 77.2090),
    "Springfield Illinois": (39.7817, -89.6501),
    "Montana distant-nearest": (47.0, -110.0),
}
BENELUX = {"country:BE", "country:NL", "country:LU"}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def subset(source: Path, output: Path) -> dict[str, Any]:
    """Write only to an explicitly supplied local scratch directory."""
    manifest = json.loads((source / "manifest.json").read_text())
    data_root = source / manifest["data_root"]
    inputs: dict[str, str] = {}
    tables: list[dict[str, Any]] = []
    extra = {h3.latlng_to_cell(*point, 3) for point in CENTRES.values()}
    rectangle = h3.LatLngPoly([(48.8, 1.7), (48.8, 8), (54.1, 8), (54.1, 1.7)])
    blocks = set(h3.polygon_to_cells(rectangle, 3)) | extra
    needed: set[str] = set()
    countries: set[str] = set()
    timezone_names: set[str] = set()

    def read(table: dict[str, Any], columns: list[str] | None = None) -> pa.Table:
        path = data_root / table["path"]
        digest = sha(path)
        if digest != table["sha256"]:
            raise ValueError(f"Input checksum mismatch: {table['path']}")
        inputs[table["path"]] = digest
        return pq.read_table(path, columns=columns)

    def write(
        kind: str, rows: list[dict[str, Any]], schema: pa.Schema, **fields: str
    ) -> None:
        name = f"{kind}/{len(tables):05}.parquet"
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(
            pa.Table.from_pylist(rows, schema=schema),
            path,
            compression="zstd",
            compression_level=3,
            version="2.6",
            data_page_version="1.0",
            row_group_size=65536,
            use_dictionary=True,
            write_statistics=True,
            store_schema=True,
        )
        tables.append(
            dict(
                kind=kind,
                path=name,
                rows=len(rows),
                size=path.stat().st_size,
                sha256=sha(path),
                **fields,
            )
        )

    for table in manifest["tables"]:
        if table["kind"] != "cells" or table["block"] not in blocks:
            continue
        data = read(table)
        rows = [
            r
            for r in data.to_pylist()
            if table["block"] in extra or r["country_id"] in BENELUX
        ]
        for row in rows:
            needed.update(
                row[k] for k in ("country_id", "state_id", "city_id") if row[k]
            )
            if row["country_id"]:
                countries.add(row["country_id"].removeprefix("country:"))
        write("cells", rows, data.schema, block=table["block"])
    # Forward samples share this catalogue. Only committed extract IDs enlarge its
    # geographic closure; the spatial sample and its source oracle remain unchanged.
    from tools.source_fixture import read_source

    for name in ("postal", "airports", "locode", "ip", "phone"):
        extract_path = ROOT / f"tests/fixtures/{name}-source.json.gz"
        if extract_path.exists():
            context = read_source(extract_path)
            for row in context["rows"]:
                for field in ("country_id", "state_id", "city_id", "place_id"):
                    if row.get(field):
                        needed.add(row[field])
                needed.update(row.get("place_ids") or [])
            needed.update(v for v in context.get("place_to_city", {}).values() if v)
    # Read relevant country catalogues in Arrow batches; do not materialize a
    # country's millions of records as Python dictionaries at once.
    selected: dict[str, dict[str, Any]] = {}
    columns = [
        "place_id",
        "name",
        "name_en",
        "local_name",
        "role",
        "settlement_kind",
        "country_code",
        "code",
        "code_status",
        "parent_method",
        "normalization_method",
        "parent_id",
        "sovereign_id",
        "normalized_city_id",
        "population",
        "source_ids",
        "name_provenance",
    ]
    place_schema: pa.Schema | None = None
    while needed - selected.keys():
        previous = len(selected)
        countries.update(
            v.removeprefix("country:") for v in needed if v.startswith("country:")
        )
        for table in manifest["tables"]:
            if table["kind"] != "places" or table["country"] not in countries:
                continue
            path = data_root / table["path"]
            digest = sha(path)
            if digest != table["sha256"]:
                raise ValueError(f"Input checksum mismatch: {path}")
            inputs[table["path"]] = digest
            for batch in pq.ParquetFile(path).iter_batches(
                batch_size=1024, columns=columns
            ):
                place_schema = batch.schema
                for row in batch.to_pylist():
                    if row["place_id"] not in needed:
                        continue
                    selected[row["place_id"]] = row
                    needed.update(
                        row[k]
                        for k in ("parent_id", "sovereign_id", "normalized_city_id")
                        if row[k]
                    )
                    needed.add("country:" + row["country_code"])
        if len(selected) == previous:
            raise ValueError(f"Missing catalogue closure: {needed - selected.keys()}")
    assert place_schema is not None
    write("places", [selected[k] for k in sorted(selected)], place_schema)
    for table in manifest["tables"]:
        kind = table["kind"]
        if kind in {"canonical_cities", "place_to_city"}:
            if table["country"] not in countries:
                continue
            data = read(table)
            field = "city_id" if kind == "canonical_cities" else "place_id"
            rows = [r for r in data.to_pylist() if r[field] in needed]
        elif kind in {"countries", "subdivisions"}:
            data = read(table)
            rows = [
                r
                for r in data.to_pylist()
                if r["country_code"] in countries
                and (
                    kind == "countries"
                    or r["place_id"] in needed
                    or any(p in needed for p in r["place_ids"])
                )
            ]
        elif kind == "timezone_cells":
            data = read(table)
            rows = [
                r
                for r in data.to_pylist()
                if (
                    h3.cell_to_parent(r["h3"], 3) in blocks
                    if r["h3_resolution"] >= 3
                    else any(
                        h3.cell_to_parent(b, r["h3_resolution"]) == r["h3"]
                        for b in blocks
                    )
                )
            ]
        elif kind == "zone_tables":
            data = read(table)
            rows = [r for r in data.to_pylist() if r["tzid"] in timezone_names]
        else:
            continue
        if kind == "timezone_cells":
            timezone_names.update(r["tzid"] for r in rows)
        if rows:
            write(kind, rows, data.schema)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "golden-2",
                "completed": True,
                "data_root": ".",
                "tables": tables,
                "normalization": manifest["normalization"],
            },
            sort_keys=True,
        )
        + "\n"
    )
    return {
        "subset_writer": {
            "pyarrow": pa.__version__,
            "parquet_version": "2.6",
            "compression": "zstd",
            "compression_level": 3,
            "data_page_version": "1.0",
            "row_group_size": 65536,
            "use_dictionary": True,
            "write_statistics": True,
            "store_schema": True,
        },
        "golden_manifest_sha256": sha(source / "manifest.json"),
        "files": inputs,
        "benelux_bounds": [48.8, 1.7, 54.1, 8],
        "additional_blocks": dict(
            zip(
                CENTRES,
                (h3.latlng_to_cell(*v, 3) for v in CENTRES.values()),
                strict=True,
            )
        ),
        "stored_blocks": len([t for t in tables if t["kind"] == "cells"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "tests/fixtures/packs/core-sample"
    )
    parser.add_argument("--dataset-version", default="2026.10")
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Refresh source expectations without writing a pack",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("Sample output must be inside this worktree")
    scratch = ROOT / ".tmp"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, prefix="sample-") as temporary:
        local = Path(temporary)
        provenance = subset(args.golden, local)
        extract(
            local,
            ROOT / "tests/fixtures/core-sample-vectors.json",
            ROOT / "tests/fixtures/core-source-extract.json",
            provenance,
        )
        if args.extract_only:
            print(json.dumps({"extract": "tests/fixtures/core-source-extract.json"}))
            return
        notices = {
            name: (args.golden / name).read_text()
            for name in ("DATA_LICENSES.md", "DATASET_CARD.md")
        }
        _core.write_pack(
            str(local),
            "core",
            str(output),
            {
                "data_version": args.dataset_version,
                "input_provenance": provenance,
                "sources": [
                    "golden dataset; source-level provenance retained in "
                    "metadata and notices"
                ],
                "attribution": (
                    "GeoNames; Overture Maps Foundation; OpenStreetMap contributors; "
                    "timezone-boundary-builder; IANA; DataHub. See retained notices."
                ),
                "notices": notices,
            },
        )
    size = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    print(
        json.dumps(
            {
                "pack": str(output.relative_to(ROOT)),
                "bytes": size,
                "provenance": provenance["golden_manifest_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
