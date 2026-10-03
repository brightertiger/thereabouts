"""Tiny archives exercise the actual geometry adapters without network or world data."""

import io
import json
import sqlite3
import tarfile
from pathlib import Path
from typing import Any

import shapefile
import shapely

from pipeline.runtime.ledger import Ledger
from pipeline.runtime.runner import run

from .fixtures import archive, rows, source_context

PRJ = 'GEOGCS["GCS_WGS_1984",DATUM["WGS_1984"],UNIT["Degree",0.0174532925199433]]'


def shapes(root: Path, fields: list[str], records: list[list[str]]) -> dict[str, bytes]:
    stem = root / "fixture"
    with shapefile.Writer(str(stem), shapeType=shapefile.POLYGON) as writer:
        for field in fields:
            writer.field(field, "C", size=80)
        for record in records:
            writer.poly([[(0, 0), (0, 0.01), (0.01, 0.01), (0.01, 0), (0, 0)]])
            writer.record(*record)
    stem.with_suffix(".prj").write_text(PRJ)
    return {path.name: path.read_bytes() for path in root.glob("fixture.*")}


def test_boundaries_keep_ids_licences_and_country_mapping(tmp_path: Path) -> None:
    members = shapes(
        tmp_path,
        ["shapeName", "shapeISO", "shapeID", "shapeType"],
        [["Cafe\u0301", "GB-ENG", "boundary-id", "ADM1"]],
    )
    metadata: dict[str, Any] = {
        "boundaryISO": "GBR",
        "boundaryType": "ADM1",
        "boundaryID": "GBR-ADM1-test",
        "boundaryLicense": "CC BY-SA 2.0",
        "boundarySource": "Synthetic contributor",
        "licenseSource": "example.test/licence",
        "admUnitCount": "1",
    }
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "geoboundaries",
            {
                "boundaries.zip": (
                    archive(members),
                    {"metadata": metadata, "commit": "a" * 40},
                ),
            },
        )
        source.pin.inventory["country_reference"] = {"GBR": {"alpha2": "GB"}}
        run(source.runtime, stages)
        [row] = rows(source, "areas")
        assert (row["source_id"], row["country_code"], row["subdivision_code"]) == (
            "boundary-id",
            "GB",
            "GB-ENG",
        )
        assert row["name"] == "Café" and row["license"] == "CC BY-SA 2.0"
        assert json.loads(row["provenance"])["commit"] == "a" * 40
        assert not list(source.work.rglob("*.shp"))


def test_land_verifies_publisher_count_and_preserves_overlaps(tmp_path: Path) -> None:
    members = shapes(tmp_path, ["FID"], [["1"], ["2"]])
    members["README.txt"] = (
        b"2 Polygon features\nDate of the data used is 2026-10-01T00:00:00Z\n"
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path, ledger, "osm_land", {"land.zip": (archive(members), {})}
        )
        run(source.runtime, stages)
        result = rows(source, "areas")
        assert len(result) == 2
        assert {row["source_id"] for row in result} == {"shp-record:0", "shp-record:1"}
        assert result[0]["geometry"] == result[1]["geometry"]
        report = json.loads(next(source.work.rglob("report.json")).read_bytes())
        assert report["rows"] == report["publisher"]["polygon_features"] == 2
        assert not report["publisher"]["path"].startswith("/")


def iana() -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as tar:
        for name in ("zone.tab", "zone1970.tab", "zonenow.tab"):
            payload = b"GB\t+0000+00000\tSynthetic/Zone\n"
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
    return output.getvalue()


def test_timezones_preserve_boundary_and_iana_licences(tmp_path: Path) -> None:
    members = shapes(tmp_path, ["tzid"], [["Synthetic/Zone"]])
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "timezones",
            {
                "timezones-with-oceans.shapefile.zip": (
                    archive(members),
                    {"license": "ODbL-1.0"},
                ),
                "timezone-names-with-oceans.json": (b'["Synthetic/Zone"]', {}),
                "tzdata-fixture.tar.gz": (iana(), {"license": "Public-Domain"}),
            },
        )
        run(source.runtime, stages)
        assert rows(source, "timezones")[0]["license"] == "ODbL-1.0"
        assert len(rows(source, "zone_tables")) == 3
        assert {row["license"] for row in rows(source, "zone_tables")} == {
            "Public-Domain"
        }
        assert rows(source, "timezone_cells")


def test_ghsl_extracts_and_decodes_a_geopackage(tmp_path: Path) -> None:
    path = tmp_path / "centres.gpkg"
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE gpkg_geometry_columns(
            table_name TEXT,column_name TEXT,srs_id INT);
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
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "ghsl",
            {"centres.zip": (archive({path.name: path.read_bytes()}), {})},
        )
        source.settings.options["expected_rows"] = 1
        run(source.runtime, stages)
        [row] = rows(source, "areas")
        assert row["source_id"] == "1" and row["xmax"] < 0.02
        assert shapely.from_wkb(row["geometry"]).covers(shapely.Point(0, 0))
