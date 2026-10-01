"""Network-free gbOpen restart, provenance, accounting and geometry tests."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
import shapefile
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import unary_union

from build_data.acquire import (
    Ledger,
    Workspace,
    fingerprint,
    geoboundaries,
    geoboundaries_config,
    geoboundaries_http,
    geoboundaries_pins,
    geoboundaries_resolve,
    geoboundaries_units,
    sha256_file,
)
from build_data.acquire import geoboundaries as acquire
from build_data.acquire import geoboundaries_normalize as normal
from build_data.acquire.geometry import repair_geometry, split_geometry
from build_data.acquire.io import write_json
from build_data.acquire.runtime import single_run


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Workspace, dict[str, Any]]:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    workspace = Workspace(tmp_path / "data")
    workspace.prepare()
    source = tmp_path / "source"
    source.mkdir()
    stem = source / "geoBoundaries-GBR-ADM1"
    with shapefile.Writer(str(stem), shapeType=5) as writer:
        for field in ("shapeName", "shapeISO", "shapeID", "shapeGroup", "shapeType"):
            writer.field(field, "C", size=80)
        writer.poly([[(0, 0), (0, 2), (2, 2), (2, 0), (0, 0)]])
        writer.record("  Cafe\u0301   Test ", "GB-ENG", "id-1", "GBR", "ADM1")
        writer.poly([[(3, 0), (5, 2), (3, 2), (5, 0), (3, 0)]])
        writer.record("Bowtie", "not-iso", "id-2", "GBR", "ADM1")
        writer.null()
        writer.record("Empty", "", "id-3", "GBR", "ADM1")
    stem.with_suffix(".prj").write_text('GEOGCS["WGS84",DATUM["WGS_1984"]]')
    metadata: dict[str, Any] = {
        "boundaryISO": "GBR",
        "boundaryType": "ADM1",
        "boundaryID": "GBR-ADM1-fixture",
        "boundaryLicense": "CC BY-SA 2.0",
        "boundarySource": "Original contributor",
        "licenseSource": "example.test/license",
        "boundaryYearRepresented": "2017",
        "sourceDataUpdateDate": "2023",
        "buildDate": "2024",
        "admUnitCount": "3",
    }
    pin: dict[str, Any] = {
        "commit": "a" * 40,
        "metadata": metadata,
        "retrieved_at": "2026-10-01",
        "url": "https://example.test/layer.zip",
        "etag": '"pinned"',
        "size": 0,
    }
    archive = geoboundaries_pins._archive_path(workspace, pin)
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for path in source.iterdir():
            target.write(path, path.name)
    pin["size"] = archive.stat().st_size
    write_json(workspace.raw(geoboundaries_config.SOURCE) / "pins/GBR-ADM1.json", pin)
    write_json(
        workspace.raw(geoboundaries_config.SOURCE) / "inventory.json",
        {
            "source_release": "test-snapshot",
            "layers": [metadata],
            "country_reference": {"GBR": {"alpha2": "GB", "population": 1}},
            "missing_in_api": {"ADM0": [], "ADM1": []},
        },
    )
    write_json(
        workspace.raw(geoboundaries_config.SOURCE) / "licenses.json",
        {"licenses": ["CC BY-SA 2.0"]},
    )
    ledger = Ledger(workspace.ledger_path)
    ledger.complete(
        "geoboundaries.download",
        "GBR-ADM1",
        fingerprint({"pin": pin, "builder": geoboundaries_config.DOWNLOAD_VERSION}),
        [archive],
    )
    return workspace, pin


def test_normalization_accounting_provenance_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _ = _fixture(tmp_path, monkeypatch)
    geoboundaries.normalize(workspace)
    root = workspace.normalized(geoboundaries_config.SOURCE)
    manifest = json.loads((root / "manifest.json").read_text())
    assert len(manifest["units"]) == 1
    summary = json.loads((root / "verification.json").read_text())
    assert summary["input_features"] == 3
    assert summary["output_rows"] == 2
    assert summary["reject_count"] == 1
    assert summary["invalid_input"] == summary["repaired_features"] == 1
    parts = list(root.rglob("*.parquet"))
    rows = [row for path in parts for row in pq.read_table(path).to_pylist()]
    row = rows[0]
    assert row["name"] == "Café Test"
    assert row["name_en"] is None
    assert row["country_code"] == "GB" and row["subdivision_code"] == "GB-ENG"
    assert rows[1]["subdivision_code"] is None
    assert row["license"] == "CC BY-SA 2.0"
    assert row["admin_level"] == row["subtype"] == "ADM1"
    provenance = json.loads(row["provenance"])
    assert provenance["source_properties"]["shapeName"] == "Cafe\u0301   Test"
    assert provenance["layer_metadata"]["boundaryYearRepresented"] == "2017"
    assert not list((workspace.work / geoboundaries_config.SOURCE).iterdir())
    previous = {path: (path.stat().st_mtime_ns, sha256_file(path)) for path in parts}

    def no_conversion(*args: object, **kwargs: object) -> None:
        raise AssertionError("Completed units must not transform again")

    monkeypatch.setattr(normal, "_convert", no_conversion)
    geoboundaries.normalize(workspace)
    assert previous == {
        path: (path.stat().st_mtime_ns, sha256_file(path)) for path in parts
    }


def test_split_preserves_area_and_holes(monkeypatch: pytest.MonkeyPatch) -> None:
    polygon = Point(0, 0).buffer(10, quad_segs=64).difference(box(-2, -2, 2, 2))
    pieces = list(split_geometry(polygon, 700, flatten_intersections=True))
    assert len(pieces) > 1
    assert all(piece.is_valid and len(piece.wkb) <= 700 for piece in pieces)
    assert unary_union(pieces).symmetric_difference(polygon).area < 1e-10
    multi = MultiPolygon([box(i * 2, 0, i * 2 + 1, 1) for i in range(40)])
    parts = list(split_geometry(multi, 700, flatten_intersections=True))
    assert unary_union(parts).equals(multi)
    assert all(len(part.wkb) <= 700 for part in parts)


def test_publisher_mismatch_blocks_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, pin = _fixture(tmp_path, monkeypatch)
    pin["metadata"]["admUnitCount"] = "4"
    pin["archive_sha256"] = sha256_file(
        geoboundaries_pins._archive_path(workspace, pin)
    )
    with pytest.raises(ValueError, match="Publisher feature count mismatch"):
        geoboundaries_units._convert(
            workspace,
            pin,
            "GB",
            "b" * 64,
            workspace.work / geoboundaries_config.SOURCE / "test",
        )
    assert not (
        workspace.normalized(geoboundaries_config.SOURCE) / "manifest.json"
    ).exists()


def test_failed_download_is_not_empty_and_does_not_stop_other_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _ = _fixture(tmp_path, monkeypatch)
    inventory = geoboundaries_http._read(
        workspace.raw(geoboundaries_config.SOURCE) / "inventory.json"
    )
    inventory["layers"].append({"boundaryISO": "USA", "boundaryType": "ADM1"})
    monkeypatch.setattr(acquire, "_inventory", lambda workspace: inventory)
    original_pin = geoboundaries_pins._pin

    def failing_pin(workspace: Workspace, layer: dict[str, Any]) -> dict[str, Any]:
        if layer["boundaryISO"] == "USA":
            raise OSError("Offline")
        return original_pin(workspace, layer)

    monkeypatch.setattr(acquire, "_pin", failing_pin)
    with pytest.raises(RuntimeError, match="1 geoBoundaries layers failed"):
        geoboundaries.download(workspace)
    report = geoboundaries_http._read(
        workspace.work / "geoboundaries-download-report.json"
    )
    assert list(report["completed"]) == ["GBR-ADM1"]
    assert report["failed"] == {"USA-ADM1": "OSError: Offline"}
    assert report["finished"]


def test_lock_prevents_duplicate_writers(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    with (
        single_run(workspace, "geoboundaries"),
        pytest.raises(RuntimeError, match="Another geoboundaries"),
        single_run(workspace, "geoboundaries"),
    ):
        pytest.fail("Duplicate writer was admitted")


def test_bounds_and_empty_geometry_rejects() -> None:
    with pytest.raises(ValueError, match="Empty"):
        repair_geometry(Polygon(), clip_roundoff=True)
    with pytest.raises(ValueError, match="outside WGS84"):
        repair_geometry(box(179, 0, 181, 1), clip_roundoff=True)
    repaired, changes = repair_geometry(box(179, 0, 180 + 1e-10, 1), clip_roundoff=True)
    assert repaired.bounds[2] == 180
    assert changes == ["clip_sub_1e-8_degree_world_bound_roundoff"]


def test_inventory_resolves_mislisted_layer_without_overwriting_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    faulty: dict[str, Any] = {
        "boundaryISO": "IND",
        "boundaryType": "ADM1",
        "boundaryID": "IND-ADM0-bad",
        "boundaryLicense": "old licence",
    }
    proper: dict[str, Any] = dict(faulty, boundaryID="IND-ADM1-good")
    replacement: dict[str, Any] = dict(
        faulty, boundaryType="ADM0", boundaryID="IND-ADM0-good", boundaryLicense="CC0"
    )
    original = {
        "layers": [faulty, proper],
        "country_reference": {"IND": {"population": 1}, "ANT": {}, "SCG": {}},
    }
    monkeypatch.setattr(
        geoboundaries_resolve,
        "_metadata",
        lambda url, path: {"url": url, "body": json.dumps(replacement)},
    )
    resolved = geoboundaries_resolve._resolve_inventory(workspace, original)
    assert [geoboundaries_config._unit(layer) for layer in resolved["layers"]] == [
        "IND-ADM0",
        "IND-ADM1",
    ]
    assert resolved["missing_in_api"] == {"ADM0": [], "ADM1": []}
    assert resolved["inventory_corrections"][0]["original"] == faulty
    assert original["layers"] == [faulty, proper]
    assert geoboundaries_resolve._resolve_inventory(workspace, original) == resolved
    path = workspace.raw(geoboundaries_config.SOURCE) / "pins/IND-ADM1.json"
    write_json(path, {"metadata": faulty})
    assert geoboundaries_pins._pin_path(workspace, proper) != path
    assert geoboundaries_http._read(path)["metadata"] == faulty


def test_split_failure_does_not_publish_partial_feature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterator

    from shapely.geometry.base import BaseGeometry

    workspace, pin = _fixture(tmp_path, monkeypatch)
    pin["archive_sha256"] = sha256_file(
        geoboundaries_pins._archive_path(workspace, pin)
    )

    def fail_after_part(
        geometry: BaseGeometry, max_bytes: int, **kwargs: object
    ) -> Iterator[BaseGeometry]:
        yield box(0, 0, 1, 1)
        raise ValueError("Synthetic subdivision failure")

    monkeypatch.setattr(geoboundaries_units, "split_geometry", fail_after_part)
    outputs, report = geoboundaries_units._convert(
        workspace,
        pin,
        "GB",
        "c" * 64,
        workspace.work / geoboundaries_config.SOURCE / "test",
    )
    assert outputs == []
    assert report["reject_count"] == report["input_features"] == 3
    assert report["output_rows"] == 0


@pytest.mark.parametrize("range_status", [200, 206])
def test_only_proven_range_routes_enter_worklist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, range_status: int
) -> None:
    import io
    from http.client import HTTPResponse
    from typing import cast

    workspace = Workspace(tmp_path)
    layer: dict[str, Any] = {
        "boundaryISO": "GBR",
        "boundaryType": "ADM1",
        "staticDownloadLink": "https://github.com/wmgeolab/geoBoundaries/raw/aaaaaaa/releaseData/gbOpen/GBR/ADM1/layer.zip",
    }
    monkeypatch.setattr(
        geoboundaries_pins,
        "_metadata",
        lambda url, path: {"body": json.dumps({"sha": "a" * 40})},
    )

    class Response(io.BytesIO):
        def __init__(self, status: int, data: bytes) -> None:
            super().__init__(data)
            self.status = status

        def getheader(self, name: str, default: str | None = None) -> str | None:
            return {
                "Content-Length": "100",
                "ETag": '"strong"',
                "Content-Range": "bytes 0-31/100",
            }.get(name, default)

    def request(
        url: str, *, method: str = "GET", headers: dict[str, str] | None = None
    ) -> HTTPResponse:
        assert "a" * 40 in url
        if method == "HEAD":
            return cast(HTTPResponse, Response(200, b""))
        assert headers == {"Range": "bytes=0-31", "If-Range": '"strong"'}
        return cast(HTTPResponse, Response(range_status, b"x" * 32))

    monkeypatch.setattr(geoboundaries_pins, "_request", request)
    if range_status == 206:
        pin = geoboundaries_pins._pin(workspace, layer)
        assert pin["range_verified"] and pin["commit"] == "a" * 40
    else:
        with pytest.raises(ValueError, match="range probe"):
            geoboundaries_pins._pin(workspace, layer)
        assert not geoboundaries_pins._pin_path(workspace, layer).exists()


def test_source_count_discrepancy_is_audited_when_formats_agree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, pin = _fixture(tmp_path, monkeypatch)
    archive = geoboundaries_pins._archive_path(workspace, pin)
    with zipfile.ZipFile(archive, "a") as target:
        target.writestr(
            "layer.geojson",
            json.dumps(
                {
                    "features": [
                        {"properties": {"shapeID": f"id-{i}"}} for i in (1, 2, 3)
                    ]
                }
            ),
        )
    pin["metadata"]["admUnitCount"] = "4"
    pin["archive_sha256"] = sha256_file(archive)
    _, report = geoboundaries_units._convert(
        workspace,
        pin,
        "GB",
        "d" * 64,
        workspace.work / geoboundaries_config.SOURCE / "test",
    )
    assert report["published_feature_count"] == 4
    assert report["input_features"] == 3
    assert not report["publisher_count_matches"]
    assert report["count_discrepancy"]["geojson_count"] == 3
    assert report["count_discrepancy"]["geometry_ids_match"]


def test_geojson_id_audit_crosses_chunks_and_ignores_geometry_strings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    from build_data.acquire import geoboundaries_json as scan

    monkeypatch.setattr(scan, "CHUNK_BYTES", 7)
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[1, 2], [3, 4]]]},
                "properties": {
                    "shapeName": 'shapeID "not-an-id" {}[]',
                    "shapeID": "a\\b",
                },
            },
            {
                "properties": {"shapeID": "second", "shapeName": "shapeID"},
                "geometry": {"coordinates": []},
            },
        ],
    }
    assert scan.feature_ids(io.BytesIO(json.dumps(payload).encode())) == [
        "a\\b",
        "second",
    ]
    with pytest.raises(ValueError, match=r"Unterminated|Incomplete"):
        scan.feature_ids(io.BytesIO(b'{"features": [{"properties": {"shapeID": "cut'))


def test_source_budget_includes_work_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    workspace.work.mkdir()
    (workspace.work / "geoboundaries-download.log").write_bytes(b"12345")
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    from build_data.acquire.runtime import SOURCE_LIMITS, source_budget

    monkeypatch.setitem(SOURCE_LIMITS, "geoboundaries", 4)
    with pytest.raises(OSError, match="GB budget"):
        source_budget(workspace, "geoboundaries", 0)
