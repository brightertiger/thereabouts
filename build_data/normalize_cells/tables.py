"""Publish normalized place semantics and refreshed spatial joins beside v1."""

import os
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from build_data.acquire import Workspace, atomic_output
from build_data.acquire.artifacts import file_record
from build_data.cities.engine import Engine
from build_data.cities.mapping import export as map_export
from build_data.cities.urban import Urban
from build_data.golden import paths as data_paths
from build_data.golden.inputs import Inputs
from build_data.golden.joins import export as joins_export
from build_data.golden.ledger import Ledger
from build_data.golden.storage import check_parquet
from build_data.reconcile.common import Row

SPATIAL = {"postal_codes", "airports", "trade_locations", "ip_ranges"}


def places(
    workspace: Workspace,
    output: Path,
    base: Row,
    normalized: Row,
    inputs: Inputs,
    urban: Urban,
) -> list[Row]:
    results = []
    ledger = Ledger(workspace)
    for record in base["tables"]:
        if record["kind"] != "places":
            continue
        cc = record["country"]
        report = normalized["countries"][cc]
        engine = Engine(
            Path(report["index"]["path"]), inputs.paths[cc], urban, normalized["policy"]
        )
        mapping = map_export(workspace, report, engine)
        canonical = report["table"]
        for table in [mapping, canonical]:
            target = output / table["kind"] / f"{cc}.parquet"
            link(Path(table["path"]), target)
            results.append({**table, **file_record(target)})
        digest = data_paths.digest(
            {"base": record, "normalization": report["digest"], "mapping": mapping},
            workspace.root,
        )
        path = output / "places" / f"{cc}.parquet"
        receipt = output / "checkpoints" / f"places-{cc}.json"
        unit = data_paths.relative(output, workspace.root) + ":" + cc
        if ledger.is_complete("normalize-cells.places", unit, digest):
            results.append(data_paths.read(receipt, workspace.root))
            continue
        db = duckdb.connect()
        try:
            db.execute("SET memory_limit='256MB'")
            db.execute("SET threads=1")
            db.read_parquet(record["path"]).create_view("places")
            db.read_parquet(mapping["path"]).create_view("mapping")
            db.read_parquet(canonical["path"]).create_view("cities")
            query = """SELECT p.* EXCLUDE(name,role),
              coalesce(c.name,p.name) AS name,
              CASE WHEN c.kind IS NOT NULL THEN c.kind
                   WHEN p.role='city' THEN 'settlement' ELSE p.role END AS role,
              m.city_id AS normalized_city_id,m.method AS normalization_method,
              CASE WHEN c.kind IS NOT NULL THEN c.kind
                   WHEN m.city_id<>p.place_id THEN 'city_part'
                   WHEN p.role='city' THEN coalesce(p.settlement_class,'settlement')
                   ELSE p.role END AS settlement_kind
              FROM places p LEFT JOIN mapping m USING(place_id)
              LEFT JOIN cities c USING(place_id)"""
            with atomic_output(path, check_parquet) as temporary:
                db.sql(query).write_parquet(
                    str(temporary), compression="zstd", row_group_size=16384
                )
        finally:
            db.close()
        count = pq.read_metadata(path).num_rows
        if count != record["rows"]:
            raise ValueError("Normalization changed catalogue cardinality")
        result = {**file_record(path), "kind": "places", "country": cc, "rows": count}
        data_paths.write(receipt, result, workspace.root)
        ledger.complete("normalize-cells.places", unit, digest, [path, receipt])
        results.append(result)
        print(f"v2 places {cc}: {count}", flush=True)
    return results


def link(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if os.path.samefile(source, target):
            return
        target.unlink()
    os.link(source, target)


def lookups(
    workspace: Workspace, output: Path, base: Row, cells: list[Row]
) -> list[Row]:
    result = joins_export(
        workspace, cells, output=output, stage="normalize-cells.lookup"
    )
    for record in base["tables"]:
        if record["kind"] in {"places", "cells", *SPATIAL}:
            continue
        source = Path(record["path"])
        target = output / "lookups" / record["kind"] / source.name
        link(source, target)
        result.append({**record, **file_record(target)})
    return result
