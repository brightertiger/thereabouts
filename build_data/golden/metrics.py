"""Exact represented-centre coverage and canonical foreign-key accounting."""

from __future__ import annotations

import duckdb
from h3.api import basic_int as h3

from build_data.acquire import Workspace
from build_data.reconcile.common import Row


def scalar(db: duckdb.DuckDBPyConnection, sql: str) -> int:
    result = db.execute(sql).fetchone()
    assert result is not None
    return int(result[0])


def measure(workspace: Workspace, places: list[Row], cells: list[Row]) -> Row:
    if not places or not cells:
        return {"status": "no places or cells yet"}
    db = duckdb.connect()
    db.execute("SET memory_limit='512MB'")
    db.execute("SET threads=1")
    db.execute("SET temp_directory=?", [str(workspace.work / "golden" / "spill")])
    db.execute("SET max_temp_directory_size='512MB'")
    try:
        db.read_parquet(
            [p["path"] for p in places if p["kind"] == "places"]
        ).create_view("places")
        db.read_parquet([p["path"] for p in cells]).create_view("cells")
        pentagons = ",".join(
            str(c) for level in range(3, 9) for c in h3.get_pentagons(level)
        )
        db.execute(f"""CREATE VIEW weighted AS SELECT *,
            CASE WHEN h3_uint64 IN ({pentagons})
            THEN (5 * (7::BIGINT ** (8-h3_resolution)::INTEGER) + 1) / 6
            ELSE 7::BIGINT ** (8-h3_resolution)::INTEGER END::BIGINT AS fine
            FROM cells""")
        filters = {
            "eligible": "true",
            "country": "country_id IS NOT NULL",
            "state": "state_id IS NOT NULL",
            "city": "city_id IS NOT NULL",
            "city_area": (
                "city_method IN ('area','city_polygon',"
                "'policy_polygon','rural_polygon')"
            ),
            "city_nearest": (
                "city_method IN ('nearest','rural_nearest','rural_nearest_distant')"
            ),
            "city_urban_allocation": "city_method='urban_allocation'",
            "city_town_radius": "city_method='town_radius'",
            "city_distant": "city_method='rural_nearest_distant'",
            "offshore": "land_method='offshore'",
        }
        expression = ",".join(
            f"coalesce(sum(fine) FILTER (WHERE {condition}),0)"
            for condition in filters.values()
        )
        result = db.execute(f"SELECT {expression} FROM weighted").fetchone()
        assert result is not None
        coverage = dict(zip(filters, map(int, result), strict=True))
        duplicates = scalar(
            db,
            "SELECT count(*) FROM (SELECT place_id FROM places "
            "GROUP BY 1 HAVING count(*)>1)",
        )
        db.execute(
            "CREATE TEMP TABLE place_refs AS SELECT DISTINCT "
            "unnest([country_id,state_id,city_id]) AS id FROM cells"
        )
        missing_cells = scalar(
            db,
            "SELECT count(*) FROM place_refs r ANTI JOIN places p "
            "ON r.id=p.place_id WHERE r.id IS NOT NULL",
        )
        missing_parents = scalar(
            db,
            "SELECT count(*) FROM places a ANTI JOIN places p "
            "ON a.parent_id=p.place_id WHERE a.parent_id IS NOT NULL",
        )
        missing_sovereigns = scalar(
            db,
            "SELECT count(*) FROM places a ANTI JOIN places p "
            "ON a.sovereign_id=p.place_id WHERE a.sovereign_id IS NOT NULL",
        )
        return {
            "represented_r8_centres": coverage,
            "duplicate_place_ids": duplicates,
            "missing_cell_place_ids": missing_cells,
            "missing_parent_rows": missing_parents,
            "missing_sovereign_rows": missing_sovereigns,
        }
    finally:
        db.close()
