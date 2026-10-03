"""Synthetic, offline OSM ZIP/SHX, overlap, audit and recovery tests."""

from __future__ import annotations

import struct
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
import shapefile
import shapely
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient

from pipeline.runtime.ledger import Ledger
from pipeline.sources.contract import SourceContext
from pipeline.sources.osm_land import reader as osm_land_reader
from pipeline.sources.osm_land import rows as osm_land_rows
from pipeline.sources.shared.archives import extract
from tests.pipeline.sources.fixtures import source_context

PRJ = 'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984"],UNIT["Degree",0.0174532925199433]]'


def _shapefile(path: Path, geometries: list[Polygon]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with shapefile.Writer(str(path), shapeType=shapefile.POLYGON) as writer:
        writer.field("FID", "N", 10)
        for index, geometry in enumerate(geometries):
            geometry = orient(geometry, sign=-1)
            writer.poly(
                [
                    list(geometry.exterior.coords),
                    *(list(ring.coords) for ring in geometry.interiors),
                ]
            )
            writer.record(index)
    path.with_suffix(".prj").write_text(PRJ)


@pytest.fixture
def acquired(tmp_path: Path) -> Iterator[SourceContext]:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx, _ = source_context(
            tmp_path, ledger, "osm_land", {"land.zip": (b"test", {})}
        )
        yield ctx


def test_holes_are_retained_and_not_filled(
    tmp_path: Path, acquired: SourceContext
) -> None:
    shp = tmp_path / "holes.shp"
    polygon = Polygon(
        [(0, 0), (0, 4), (4, 4), (4, 0)], [[(1, 1), (3, 1), (3, 3), (1, 3)]]
    )
    _shapefile(shp, [polygon])
    with shapefile.Reader(str(shp)) as reader:
        row, audit = osm_land_rows._row(
            acquired,
            *osm_land_reader._feature(reader, 0),
            0,
            {"attribution": "OSM", "retrieved_at": "date"},
            "0" * 64,
        )
    assert shapely.from_wkb(cast(bytes, row["geometry"])).equals(polygon)
    assert audit is None


def test_invalid_polygon_repair_is_audited(
    tmp_path: Path, acquired: SourceContext
) -> None:
    shp = tmp_path / "invalid.shp"
    _shapefile(shp, [Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])])
    with shapefile.Reader(str(shp)) as reader:
        row, audit = osm_land_rows._row(
            acquired,
            *osm_land_reader._feature(reader, 0),
            0,
            {"attribution": "OSM", "retrieved_at": "date"},
            "0" * 64,
        )
    assert audit is not None
    assert audit["repair"] == "shapely.make_valid"
    assert shapely.from_wkb(cast(bytes, row["geometry"])).is_valid


def test_shx_corruption_detected(tmp_path: Path) -> None:
    shp = tmp_path / "source.shp"
    _shapefile(shp, [box(0, 0, 1, 1)])
    with shp.with_suffix(".shx").open("r+b") as stream:
        stream.seek(100)
        stream.write(struct.pack(">i", 51))
    with pytest.raises(ValueError, match="Broken SHX"):
        list(osm_land_reader._records(shp, 1_000_000))


def test_unit_limits_keep_every_record(tmp_path: Path, acquired: SourceContext) -> None:
    shp, index = tmp_path / "source.shp", tmp_path / "index.sqlite3"
    _shapefile(shp, [box(i / 10, 0, i / 10 + 0.01, 0.01) for i in range(7)])
    assert osm_land_reader._build_index(acquired, shp, index) == 7
    acquired.settings.options["unit_records"] = 2
    units = list(osm_land_reader._units(acquired, index))
    assert [ordinal for _, records, _ in units for ordinal in records] == list(range(7))
    assert all(len(records) <= 2 for _, records, _ in units)
    acquired.settings.options["unit_records"] = 1000
    acquired.settings.options["unit_bytes"] = 240
    assert all(
        len(records) == 1 for _, records, _ in osm_land_reader._units(acquired, index)
    )


@pytest.mark.parametrize(
    "filename", ["../escape", "/absolute", "dir/../../escape", "bad\\path"]
)
def test_zip_paths_cannot_escape(
    tmp_path: Path, filename: str, acquired: SourceContext
) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(filename, b"payload")
    with pytest.raises(ValueError, match="workspace-relative"):
        extract(acquired, archive, tmp_path / "extracted", lambda _: True)


def test_publisher_count_mismatch_blocks(
    tmp_path: Path, acquired: SourceContext
) -> None:
    (tmp_path / "README.txt").write_text(
        "2 Polygon features\nDate of the data used is date\n"
    )
    with pytest.raises(ValueError, match="counts disagree"):
        osm_land_reader._publisher_notice(acquired, tmp_path / "source.shp", 1)


def test_crc_failure_does_not_publish_member(
    tmp_path: Path, acquired: SourceContext
) -> None:
    archive = tmp_path / "broken.zip"
    payload = b"crc-check-this-payload"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("source.txt", payload)
    damaged = archive.read_bytes().replace(payload, b"x" + payload[1:])
    archive.write_bytes(damaged)
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        extract(acquired, archive, tmp_path / "extracted", lambda _: True)
    assert not (tmp_path / "extracted/source.txt").exists()


def test_unrecoverable_geometry_blocks_output(
    tmp_path: Path, acquired: SourceContext
) -> None:
    shp = tmp_path / "degenerate.shp"
    _shapefile(shp, [Polygon([(0, 0), (1, 0), (2, 0), (0, 0)])])
    with (
        shapefile.Reader(str(shp)) as reader,
        pytest.raises(ValueError, match="cannot normalize losslessly"),
    ):
        osm_land_rows._row(
            acquired,
            *osm_land_reader._feature(reader, 0),
            0,
            {"attribution": "OSM", "retrieved_at": "date"},
            "0" * 64,
        )
    assert not list(acquired.normalized.rglob("*.parquet"))
