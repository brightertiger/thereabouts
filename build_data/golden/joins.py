"""Bounded joins from distinct source r8 keys to sorted compact-cell intervals."""

from __future__ import annotations

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from build_data.acquire import Ledger, Workspace, atomic_output
from build_data.acquire.artifacts import file_record
from build_data.acquire.io import fingerprint
from build_data.acquire.ledger import read_units
from build_data.acquire.manifests import load_manifest
from build_data.reconcile.common import Row

from .storage import budget, check_parquet

PARENT_MASK = ((1 << 64) - 1) ^ (15 << 52)


def prepare(db: duckdb.DuckDBPyConnection, cells: list[Row]) -> dict[int, list[str]]:
    groups: dict[int, list[str]] = {}
    for record in cells:
        parent = h3.cell_to_parent(int(record["block"], 16), 1)
        groups.setdefault(parent, []).append(record["path"])
    ready = pa.table(
        {"root": pa.array([int(r["block"], 16) for r in cells], type=pa.uint64())}
    )
    db.register("ready", ready)
    return groups


def intervals(db: duckdb.DuckDBPyConnection, paths: list[str]) -> None:
    db.read_parquet(paths).create_view("cells")
    db.execute(f"""CREATE OR REPLACE TEMP VIEW intervals AS
      SELECT ((h3_uint64 & {PARENT_MASK}::UBIGINT &
        ~((1::UBIGINT << (3 * (15 - h3_resolution::INTEGER))) - 1)) |
        (8::UBIGINT << 52) | ((1::UBIGINT << 21) - 1)) AS lo,
      ((h3_uint64 & {PARENT_MASK}::UBIGINT) | (8::UBIGINT << 52)) AS hi,
      country_id,state_id,city_id FROM cells""")


def assignments(db: duckdb.DuckDBPyConnection, groups: dict[int, list[str]]) -> None:
    """Sort narrow unique keys once per source, not its full provenance rows.

    ASOF selects the greatest lower endpoint; the upper check rejects gaps.
    Avoid the native two-inequality IEJoin path, which crashes on the pinned
    DuckDB build for the real UN/LOCODE nullable coordinate workload.
    """
    root = (
        f"((s.h3_uint64 & {PARENT_MASK}::UBIGINT) | "
        "(3::UBIGINT << 52) | ((1::UBIGINT << 36) - 1))"
    )
    db.execute(f"""CREATE OR REPLACE TEMP TABLE keys AS SELECT DISTINCT h3_uint64,
      ((h3_uint64 & {PARENT_MASK}::UBIGINT) | (1::UBIGINT << 52) |
       ((1::UBIGINT << 42)-1)) AS parent FROM source
       WHERE h3_uint64 IS NOT NULL""")
    db.execute(
        "CREATE OR REPLACE TEMP TABLE assignments(h3_uint64 UBIGINT,"
        "country_id VARCHAR,state_id VARCHAR,city_id VARCHAR,"
        "cell_country_code VARCHAR,cell_status VARCHAR)"
    )
    for (parent,) in db.execute(
        "SELECT DISTINCT parent FROM keys ORDER BY 1"
    ).fetchall():
        paths = groups.get(parent)
        if not paths:
            db.execute(
                "INSERT INTO assignments SELECT h3_uint64,NULL,NULL,NULL,"
                "NULL,'pending' FROM keys WHERE parent=?",
                [parent],
            )
            continue
        intervals(db, paths)
        db.execute(
            f"""INSERT INTO assignments
          SELECT s.h3_uint64,
            CASE WHEN s.h3_uint64<=i.hi THEN i.country_id END,
            CASE WHEN s.h3_uint64<=i.hi THEN i.state_id END,
            CASE WHEN s.h3_uint64<=i.hi THEN i.city_id END,
            CASE WHEN s.h3_uint64<=i.hi THEN substr(i.country_id,9) END,
            CASE WHEN r.root IS NULL THEN 'pending'
                 WHEN i.lo IS NULL OR s.h3_uint64>i.hi THEN 'ineligible'
                 WHEN i.country_id IS NULL THEN 'unassigned'
                 ELSE 'matched' END
          FROM (SELECT h3_uint64 FROM keys WHERE parent=?) s
          ASOF LEFT JOIN intervals i ON s.h3_uint64>=i.lo
          LEFT JOIN ready r ON {root}=r.root""",
            [parent],
        )


def export(workspace: Workspace, cells: list[Row]) -> list[Row]:
    db = duckdb.connect()
    db.execute("SET memory_limit='512MB'")
    db.execute("SET threads=1")
    db.execute("SET preserve_insertion_order=false")
    db.execute("SET temp_directory=?", [str(workspace.work / "golden" / "spill")])
    db.execute("SET max_temp_directory_size='512MB'")
    cell_digest = fingerprint({r["block"]: r["sha256"] for r in cells})
    ledger = Ledger(workspace.ledger_path)
    previous = {
        r["unit_id"]: r for r in read_units(workspace.ledger_path, "golden.lookup")
    }
    output = []
    try:
        groups = prepare(db, cells)
        for source in ("postal", "airports", "unlocode", "dbip"):
            manifest = load_manifest(workspace, source)
            parts = manifest["partitions"]
            if not parts:
                continue
            kind = parts[0]["kind"]
            if any(p["kind"] != kind for p in parts):
                raise ValueError("A spatial lookup source must contain one kind")
            digest = fingerprint({"parts": parts, "cells": cell_digest, "join": 4})
            if ledger.is_complete("golden.lookup", kind, digest):
                output.append(previous[kind]["metadata"]["table"])
                continue
            budget(workspace, required=512_000_000)
            print(f"lookups {source}: join unique reference cells", flush=True)
            db.read_parquet([p["path"] for p in parts]).create_view("source")
            assignments(db, groups)
            query = """SELECT s.*, a.country_id,a.state_id,a.city_id,
              a.cell_country_code, coalesce(a.cell_status,'unlocated') AS cell_status,
              CASE WHEN s.country_code IS NOT NULL AND a.country_id IS NOT NULL
                   THEN s.country_code<>a.cell_country_code END AS country_disagrees
              FROM source s LEFT JOIN assignments a USING(h3_uint64)"""
            destination = workspace.root / "golden/lookups" / kind / "joined.parquet"
            with atomic_output(destination, check_parquet) as temporary:
                db.sql(query).write_parquet(
                    str(temporary), compression="zstd", row_group_size=16384
                )
            count = pq.read_metadata(destination).num_rows
            if count != sum(p["rows"] for p in parts):
                raise ValueError("Cell ancestor join changed lookup row cardinality")
            db.read_parquet(str(destination)).create_view("joined")
            counts = dict(
                db.execute(
                    "SELECT cell_status,count(*) FROM joined GROUP BY 1"
                ).fetchall()
            )
            result = db.execute(
                "SELECT count(*) FILTER (WHERE country_disagrees),"
                "count(country_disagrees) FROM joined"
            ).fetchone()
            assert result is not None
            counts.update(disagreements=result[0], compared=result[1])
            record = {
                **file_record(destination),
                "kind": kind,
                "rows": count,
                "counts": counts,
            }
            ledger.complete(
                "golden.lookup", kind, digest, [destination], metadata={"table": record}
            )
            output.append(record)
            print(f"lookups {source}: {counts}", flush=True)
    finally:
        db.close()
    return output
