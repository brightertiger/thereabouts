"""Bounded joins of unique reference keys to compact-cell intervals."""

import duckdb
import pyarrow as pa
from h3.api import basic_int as h3

from pipeline.config.schema import H3
from pipeline.engines.reconcile.common import Row

JOIN_GROUP_RESOLUTION = 1
PARENT_MASK = ((1 << 64) - 1) ^ (15 << 52)


def prepare(db: duckdb.DuckDBPyConnection, cells: list[Row]) -> dict[int, list[str]]:
    groups: dict[int, list[str]] = {}
    for record in cells:
        parent = h3.cell_to_parent(int(record["block"], 16), JOIN_GROUP_RESOLUTION)
        groups.setdefault(parent, []).append(record["path"])
    ready = pa.table(
        {"root": pa.array([int(r["block"], 16) for r in cells], type=pa.uint64())}
    )
    db.register("ready", ready)
    return groups


def intervals(db: duckdb.DuckDBPyConnection, paths: list[str], grid: H3) -> None:
    trailing_bits = 3 * (15 - grid.cell_resolution)
    db.read_parquet(paths).create_view("cells")
    db.execute(f"""CREATE OR REPLACE TEMP VIEW intervals AS
      SELECT ((h3_uint64 & {PARENT_MASK}::UBIGINT &
        ~((1::UBIGINT << (3 * (15 - h3_resolution::INTEGER))) - 1)) |
        ({grid.cell_resolution}::UBIGINT << 52) |
        ((1::UBIGINT << {trailing_bits}) - 1)) AS lo,
      ((h3_uint64 & {PARENT_MASK}::UBIGINT) |
        ({grid.cell_resolution}::UBIGINT << 52)) AS hi,
      country_id,state_id,city_id FROM cells""")


def assignments(
    db: duckdb.DuckDBPyConnection, groups: dict[int, list[str]], grid: H3
) -> None:
    """Sort narrow unique keys once per source, not its full provenance rows.

    ASOF selects the greatest lower endpoint; the upper check rejects gaps.
    Avoid the native two-inequality IEJoin path, which crashes on the pinned
    DuckDB build for the real UN/LOCODE nullable coordinate workload.
    """
    root = (
        f"((s.h3_uint64 & {PARENT_MASK}::UBIGINT) | "
        f"({grid.block_resolution}::UBIGINT << 52) | "
        f"((1::UBIGINT << {3 * (15 - grid.block_resolution)}) - 1))"
    )
    db.execute(f"""CREATE OR REPLACE TEMP TABLE keys AS SELECT DISTINCT h3_uint64,
      ((h3_uint64 & {PARENT_MASK}::UBIGINT) | ({JOIN_GROUP_RESOLUTION}::UBIGINT << 52) |
       ((1::UBIGINT << {3 * (15 - JOIN_GROUP_RESOLUTION)})-1)) AS parent FROM source
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
        intervals(db, paths, grid)
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
