"""Read-only golden extraction shared by the small forward samples."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from tests.tools.build_sample_pack import sha

COUNTRIES = {"BE", "NL", "LU", "FR", "TR", "IN", "US"}
PLACE_COLUMNS = [
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


class Subset:
    def __init__(self, golden: Path, output: Path) -> None:
        self.manifest = json.loads((golden / "manifest.json").read_text())
        self.root = golden / self.manifest.get("data_root", ".")
        self.output = output
        self.tables: list[dict[str, Any]] = []
        self.inputs: dict[str, str] = {}
        self.mappings: dict[str, str | None] = {}
        self.digest = sha(golden / "manifest.json")

    def inventory(self, kind: str) -> list[dict[str, Any]]:
        return [t for t in self.manifest["tables"] if t["kind"] == kind]

    def batches(
        self, table: dict[str, Any], columns: list[str] | None = None
    ) -> Iterator[pa.RecordBatch]:
        path = self.root / table["path"]
        if table["path"] not in self.inputs:
            digest = sha(path)
            if digest != table["sha256"]:
                raise ValueError(f"Input checksum mismatch: {path}")
            self.inputs[table["path"]] = digest
        yield from pq.ParquetFile(path).iter_batches(batch_size=4096, columns=columns)

    def write(self, kind: str, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
        path = self.output / f"{kind}/{len(self.tables):05}.parquet"
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
        self.tables.append(
            {
                "kind": kind,
                "path": str(path.relative_to(self.output)),
                "rows": len(rows),
                "size": path.stat().st_size,
                "sha256": sha(path),
            }
        )

    def context(self, rows: list[dict[str, Any]]) -> None:
        needed = {
            r[k]
            for r in rows
            for k in ("country_id", "state_id", "city_id")
            if r.get(k)
        }
        countries = {r["country_code"] for r in rows if r.get("country_code")}
        selected: dict[str, dict[str, Any]] = {}
        schema: pa.Schema | None = None
        while needed - selected.keys():
            previous = len(selected)
            countries.update(
                v.removeprefix("country:") for v in needed if v.startswith("country:")
            )
            for table in self.inventory("places"):
                if table.get("country") not in countries:
                    continue
                for batch in self.batches(table, PLACE_COLUMNS):
                    schema = batch.schema
                    for row in batch.to_pylist():
                        if row["place_id"] in needed:
                            selected[row["place_id"]] = row
                            needed.update(
                                row[k]
                                for k in (
                                    "parent_id",
                                    "sovereign_id",
                                    "normalized_city_id",
                                )
                                if row[k]
                            )
                            needed.add("country:" + row["country_code"])
            if len(selected) == previous:
                raise ValueError(
                    f"Missing catalogue closure: {needed - selected.keys()}"
                )
        if schema is None:
            raise ValueError("Sample has no published geography")
        self.write("places", [selected[k] for k in sorted(selected)], schema)
        for kind in ("canonical_cities", "place_to_city", "countries", "subdivisions"):
            field = "city_id" if kind == "canonical_cities" else "place_id"
            for table in self.inventory(kind):
                if table.get("country") and table["country"] not in countries:
                    continue
                chosen = []
                for batch in self.batches(table):
                    schema = batch.schema
                    for row in batch.to_pylist():
                        keep = row.get(field) in needed
                        if kind == "countries":
                            keep = row["country_code"] in countries
                        if kind == "subdivisions":
                            keep = keep or any(
                                p in needed for p in row.get("place_ids") or []
                            )
                        if keep:
                            chosen.append(row)
                # Empty inventories prove the kind was deliberately supplied.
                if kind == "place_to_city":
                    self.mappings.update((r["place_id"], r["city_id"]) for r in chosen)
                self.write(kind, chosen, schema)

    def finish(self, family: str, source_rows: int) -> dict[str, Any]:
        (self.output / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "golden-2",
                    "completed": True,
                    "data_root": ".",
                    "tables": self.tables,
                },
                sort_keys=True,
            )
            + "\n"
        )
        return {
            "golden_manifest_sha256": self.digest,
            "files": self.inputs,
            "countries": sorted(COUNTRIES),
            "family": family,
            "world_source_rows": source_rows,
            "pyarrow": pa.__version__,
            "subset_policy": (
                "first 32 distinct codes per country plus named example codes; "
                "all observations of those codes"
            ),
            "parquet": {
                "version": "2.6",
                "compression": "zstd",
                "level": 3,
                "row_group_size": 65536,
            },
        }
