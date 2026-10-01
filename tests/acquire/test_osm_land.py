"""Synthetic, offline OSM ZIP/SHX, overlap, audit and recovery tests."""

from __future__ import annotations

import json
import shutil
import struct
import zipfile
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq
import pytest
import shapefile
import shapely
from shapely.geometry import Polygon, box
from shapely.geometry.polygon import orient

from build_data.acquire import (
    Ledger,
    Workspace,
    osm_land_reader,
    osm_land_rows,
    osm_land_settings,
    osm_land_units,
    sha256_file,
    validate_parquet,
)
from build_data.acquire import osm_land as source
from build_data.acquire import osm_land_normalize as normal
from build_data.acquire.runtime import single_run

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
def acquired(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    workspace = Workspace(tmp_path / "data")
    polygons = [
        box(x - 0.01, y - 0.01, x + 0.01, y + 0.01)
        for x, y, land in osm_land_settings.SPOT_CHECKS.values()
        if land
    ]
    polygons.extend([box(20, 20, 21.1, 21), box(21, 20, 22, 21)])
    fixture = tmp_path / "fixture" / "land_polygons.shp"
    _shapefile(fixture, polygons)
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for suffix in (".shp", ".shx", ".dbf", ".prj"):
            zipped.write(
                fixture.with_suffix(suffix), f"land-polygons/land_polygons{suffix}"
            )
        zipped.writestr(
            "land-polygons/README.txt",
            (
                f"{len(polygons)} Polygon features\n"
                "Date of the data used is 2026-10-01T00:00:00Z\n"
            ),
        )
    monkeypatch.setattr(source, "EXPECTED_SIZE", archive.stat().st_size)

    def local_download(url: str, destination: Path, **kwargs: Any) -> Path:
        assert url == source.SOURCE_URL
        assert kwargs["expected_size"] == archive.stat().st_size
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(archive, destination)
        return destination

    monkeypatch.setattr(source, "download_file", local_download)
    source.download(workspace)
    return workspace


def _outputs(workspace: Workspace) -> list[Path]:
    manifest = json.loads(
        (workspace.normalized("osm_land") / "manifest.json").read_text()
    )
    ledger = Ledger(workspace.ledger_path)
    paths: list[Path] = []
    for unit in manifest["units"]:
        outputs = ledger.completed_outputs(**unit)
        assert outputs is not None
        paths.extend(path for path in outputs if path.suffix == ".parquet")
    return paths


def test_normalize_preserves_geometry_overlap_and_source_counts(
    acquired: Workspace,
) -> None:
    source.normalize(acquired)
    paths = _outputs(acquired)
    rows: list[dict[str, Any]] = []
    for path in paths:
        validate_parquet(path, "areas")
        rows.extend(pq.ParquetFile(path).read().to_pylist())
    report = json.loads(
        (acquired.normalized("osm_land") / "verification.json").read_text()
    )
    assert report["rows"] == report["source_dbf_records"] == 9
    assert report["rejected_records"] == report["invalid_output_count"] == 0
    assert all(check["passed"] for check in report["spot_checks"].values())
    assert len({row["source_id"] for row in rows}) == 9
    overlapping = [
        row for row in rows if row["source_id"] in ("shp-record:7", "shp-record:8")
    ]
    geometries = [shapely.from_wkb(row["geometry"]) for row in overlapping]
    assert geometries[0].intersection(geometries[1]).area == pytest.approx(0.1)
    for row in rows:
        provenance = json.loads(row["provenance"])
        assert provenance["source_attributes"]["FID"] == int(
            row["source_id"].split(":")[1]
        )
        assert "NOT necessarily coastline" in provenance["boundary_semantics"]


def test_resume_verifies_but_does_not_transform_completed_units(
    acquired: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    source.normalize(acquired)
    hashes = {path: sha256_file(path) for path in _outputs(acquired)}

    def unexpected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Completed geometry was transformed again")

    monkeypatch.setattr(osm_land_units, "_row", unexpected)
    source.normalize(acquired)
    assert hashes == {path: sha256_file(path) for path in _outputs(acquired)}


def test_corrupt_partition_rebuilt_identically(acquired: Workspace) -> None:
    source.normalize(acquired)
    first = _outputs(acquired)[0]
    expected = sha256_file(first)
    first.write_bytes(b"broken")
    source.normalize(acquired)
    assert sha256_file(first) == expected


def test_interrupted_units_resume_without_duplicates(
    acquired: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = osm_land_units._run_unit
    calls = 0

    def interrupted(*args: Any, **kwargs: Any) -> tuple[Path, Path]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("simulated interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(normal, "_run_unit", interrupted)
    with pytest.raises(OSError, match="simulated interruption"):
        source.normalize(acquired)
    assert not (acquired.normalized("osm_land") / "manifest.json").exists()
    monkeypatch.setattr(normal, "_run_unit", original)
    source.normalize(acquired)
    assert (
        sum(pq.ParquetFile(path).metadata.num_rows for path in _outputs(acquired)) == 9
    )


def test_member_extraction_reuses_verified_members(
    acquired: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Verified ZIP member was re-extracted")

    monkeypatch.setattr(zipfile.ZipFile, "open", unexpected)
    source.download(acquired)


def test_holes_are_retained_and_not_filled(tmp_path: Path) -> None:
    shp = tmp_path / "holes.shp"
    polygon = Polygon(
        [(0, 0), (0, 4), (4, 4), (4, 0)], [[(1, 1), (3, 1), (3, 3), (1, 3)]]
    )
    _shapefile(shp, [polygon])
    with shapefile.Reader(str(shp)) as reader:
        row, audit = osm_land_rows._row(
            *osm_land_reader._feature(reader, 0),
            0,
            {"attribution": "OSM", "retrieved_at": "date"},
            "0" * 64,
        )
    assert shapely.from_wkb(cast(bytes, row["geometry"])).equals(polygon)
    assert audit is None


def test_invalid_polygon_repair_is_audited(tmp_path: Path) -> None:
    shp = tmp_path / "invalid.shp"
    _shapefile(shp, [Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])])
    with shapefile.Reader(str(shp)) as reader:
        row, audit = osm_land_rows._row(
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
        list(osm_land_reader._records(shp))


def test_unit_limits_keep_every_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shp, index = tmp_path / "source.shp", tmp_path / "index.sqlite3"
    _shapefile(shp, [box(i / 10, 0, i / 10 + 0.01, 0.01) for i in range(7)])
    assert osm_land_reader._build_index(shp, index) == 7
    monkeypatch.setattr(osm_land_reader, "MAX_UNIT_RECORDS", 2)
    units = list(osm_land_reader._units(index))
    assert [ordinal for _, records, _ in units for ordinal in records] == list(range(7))
    assert all(len(records) <= 2 for _, records, _ in units)
    monkeypatch.setattr(osm_land_reader, "MAX_UNIT_RECORDS", 1000)
    monkeypatch.setattr(osm_land_reader, "MAX_UNIT_BYTES", 240)
    assert all(len(records) == 1 for _, records, _ in osm_land_reader._units(index))


@pytest.mark.parametrize(
    "filename", ["../escape", "/absolute", "dir/../../escape", "bad\\path"]
)
def test_zip_paths_cannot_escape(tmp_path: Path, filename: str) -> None:
    with pytest.raises(ValueError, match="Unsafe ZIP"):
        source._member_path(tmp_path, zipfile.ZipInfo(filename))


def test_source_lock_rejects_duplicate_owner(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with (
        single_run(workspace, "osm_land"),
        pytest.raises(RuntimeError, match="owns the source lock"),
        single_run(workspace, "osm_land"),
    ):
        pytest.fail("Second owner entered")


def test_publisher_count_mismatch_blocks(tmp_path: Path) -> None:
    (tmp_path / "README.txt").write_text(
        "2 Polygon features\nDate of the data used is date\n"
    )
    with pytest.raises(ValueError, match="counts disagree"):
        osm_land_reader._publisher_notice(tmp_path / "source.shp", 1)


def test_crc_failure_does_not_publish_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    workspace = Workspace(tmp_path / "data")
    archive = tmp_path / "broken.zip"
    payload = b"crc-check-this-payload"
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("source.txt", payload)
    damaged = archive.read_bytes().replace(payload, b"x" + payload[1:])
    archive.write_bytes(damaged)
    with pytest.raises(zipfile.BadZipFile, match="CRC"):
        source._extract(
            workspace, archive, sha256_file(archive), Ledger(workspace.ledger_path)
        )
    assert not (tmp_path / "extracted/source.txt").exists()


def test_unrecoverable_geometry_is_reported_and_blocks_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    workspace = Workspace(tmp_path / "data")
    shp = tmp_path / "degenerate.shp"
    _shapefile(shp, [Polygon([(0, 0), (1, 0), (2, 0), (0, 0)])])
    with (
        shapefile.Reader(str(shp)) as reader,
        pytest.raises(ValueError, match="cannot normalize losslessly"),
    ):
        osm_land_units._run_unit(
            workspace,
            reader,
            {"attribution": "OSM", "retrieved_at": "date"},
            "0" * 64,
            "bad",
            [0],
            [0.0, 0.0, 2.0, 0.0],
            "1" * 64,
            Ledger(workspace.ledger_path),
        )
    audit = json.loads((workspace.work / "osm_land-rejection.json").read_text())
    assert audit["rejected_records"] == 1
    assert audit["record_index"] == 0
    assert not list(workspace.normalized("osm_land").rglob("*.parquet"))
