"""Join canonical city semantics without changing catalogue cardinality."""

from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from pipeline.runtime.jsonio import atomic_output


def places(
    db: duckdb.DuckDBPyConnection,
    base: Path,
    mapping: Path,
    canonical: Path,
    output: Path,
    batch_rows: int,
) -> None:
    db.read_parquet(str(base), file_row_number=True).create_view("places", replace=True)
    db.read_parquet(str(mapping)).create_view("mapping", replace=True)
    db.read_parquet(str(canonical)).create_view("cities", replace=True)
    query = """SELECT p.* EXCLUDE(name,role,file_row_number),
      coalesce(c.name,p.name) AS name,
      CASE WHEN c.kind IS NOT NULL THEN c.kind
           WHEN p.role='city' THEN 'settlement' ELSE p.role END AS role,
      m.city_id AS normalized_city_id,m.method AS normalization_method,
      CASE WHEN c.kind IS NOT NULL THEN c.kind
           WHEN m.city_id<>p.place_id THEN 'city_part'
           WHEN p.role='city' THEN coalesce(p.settlement_class,'settlement')
           ELSE p.role END AS settlement_kind
      FROM places p LEFT JOIN mapping m USING(place_id)
      LEFT JOIN cities c USING(place_id)
      ORDER BY p.file_row_number"""
    with atomic_output(output) as temporary:
        db.sql(query).write_parquet(
            str(temporary), compression="zstd", row_group_size=batch_rows
        )
        if pq.read_metadata(temporary).num_rows != pq.read_metadata(base).num_rows:
            raise ValueError("Normalization changed catalogue cardinality")
