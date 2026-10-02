"""GHSL decoding uses a synthetic GeoPackage, never a downloaded fixture."""

import sqlite3
from pathlib import Path

import numpy as np
import shapely

from build_data.acquire.ghsl import inverse_mollweide, records


def test_inverse_mollweide_known_equator() -> None:
    x = 2 * np.sqrt(2) * 6378137 * np.deg2rad(90) / np.pi
    result = inverse_mollweide(np.array([[0.0, 0.0], [x, 0.0]]))
    np.testing.assert_allclose(result, [[0, 0], [90, 0]], atol=1e-10)


def test_geopackage_header_and_source_evidence(tmp_path: Path) -> None:
    path = tmp_path / "source.gpkg"
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE gpkg_geometry_columns(table_name TEXT,column_name TEXT,srs_id INT);
      INSERT INTO gpkg_geometry_columns VALUES('centres','geom',54009);
      CREATE TABLE gpkg_spatial_ref_sys(srs_id INT,definition TEXT);
      INSERT INTO gpkg_spatial_ref_sys VALUES(54009,'Mollweide 6378137');
      CREATE TABLE centres(ID_UC_G0 INT,geom BLOB);
    """)
    blob = (
        b"GP\x00\x01"
        + (54009).to_bytes(4, "little")
        + shapely.box(-1000, -1000, 1000, 1000).wkb
    )
    db.execute("INSERT INTO centres VALUES(1,?)", (blob,))
    db.commit()
    db.close()
    (row,) = records(path)
    assert row["source_id"] == "1"
    assert row["license"] == "CC-BY-4.0"
    geometry = shapely.from_wkb(row["geometry"])
    assert geometry is not None
    assert geometry.covers(shapely.Point(0, 0))
    assert row["xmax"] < 0.02
