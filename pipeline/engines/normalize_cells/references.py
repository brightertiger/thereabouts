"""Count missing and cross-country normalized catalogue references."""

import duckdb

from pipeline.config.schema import Resources
from pipeline.engines.reconcile.common import Row


def reference_checks(tables: list[Row], resources: Resources) -> Row:
    db = duckdb.connect()
    db.execute("SET memory_limit=?", [resources.duckdb_memory])
    db.execute("SET threads=?", [resources.duckdb_threads])
    try:
        for kind in ("places", "canonical_cities", "place_to_city"):
            db.read_parquet(
                [r["path"] for r in tables if r["kind"] == kind]
            ).create_view(kind)
        queries = {
            "unmapped_places": (
                "SELECT count(*) FROM places p "
                "ANTI JOIN place_to_city m USING(place_id)"
            ),
            "dangling_mapping": (
                "SELECT count(*) FROM place_to_city m ANTI JOIN places p "
                "ON m.city_id=p.place_id WHERE m.city_id IS NOT NULL"
            ),
            "dangling_canonical": (
                "SELECT count(*) FROM canonical_cities c ANTI JOIN places p "
                "ON c.city_id=p.place_id"
            ),
            "cross_country_mapping": (
                "SELECT count(*) FROM place_to_city m "
                "JOIN places a ON m.place_id=a.place_id "
                "JOIN places b ON m.city_id=b.place_id "
                "WHERE a.country_code<>b.country_code"
            ),
        }
        result = {}
        for name, query in queries.items():
            row = db.execute(query).fetchone()
            if row is None:
                raise ValueError("Reference query returned no row")
            result[name] = int(row[0])
        return result
    finally:
        db.close()
