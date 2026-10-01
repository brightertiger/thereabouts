"""Offline Overture preservation, checkpoint and geometry conversion tests."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import Polygon, box

from build_data.acquire import Workspace, sha256_file, validate_table
from build_data.acquire import overture_normalize as adapter
from build_data.acquire.io import write_json
from build_data.acquire.schemas import SCHEMAS

CONTEXT = {"source_url": "https://example.test/object", "source_release": "test-1"}


def division(
    identifier: str = "point-1", subtype: str = "neighborhood"
) -> dict[str, Any]:
    return {
        "id": identifier,
        "geometry": shapely.Point(-74.0060, 40.7128).wkb,
        "names": {
            "primary": "  Cafe\u0301\t町 ",
            "common": [("en", "Test Place")],
            "rules": [{"value": "Old Test", "variant": "historic", "language": "en"}],
        },
        "subtype": subtype,
        "class": "suburb",
        "admin_level": 3,
        "country": "US",
        "region": "US-NY",
        "parent_division_id": None,
        "hierarchies": [[{"division_id": identifier, "subtype": subtype}]],
        "perspectives": {"disputed_by": ["XX"]},
        "population": 0,
        "sources": [{"dataset": "Synthetic", "record_id": "source-1"}],
    }


def area(identifier: str = "area-1") -> dict[str, Any]:
    return {
        "id": identifier,
        "division_id": "point-1",
        "geometry": box(-75, 40, -73, 42).wkb,
        "names": {"primary": "Area", "common": [("en", "Test Area")]},
        "subtype": "neighborhood",
        "class": "land",
        "country": "US",
        "region": "US-NY",
        "admin_level": 3,
        "is_land": True,
        "is_territorial": True,
    }


def test_all_roles_names_and_nested_metadata_are_preserved() -> None:
    for subtype in (
        "country",
        "dependency",
        "region",
        "locality",
        "borough",
        "microhood",
        "future-subtype",
    ):
        raw = division(subtype=subtype)
        row = adapter.place(raw, CONTEXT)
        assert row["kind"] == subtype
        assert row["name"] == "Café 町"
        assert row["name_en"] == "Test Place"
        assert row["population"] == 0
        assert row["feature_class"] == "suburb"
        provenance = json.loads(row["provenance"])
        assert provenance["upstream"]["hierarchies"] == raw["hierarchies"]
        assert provenance["upstream"]["admin_level"] == 3
        validate_table(pa.Table.from_pylist([row], schema=SCHEMAS["places"]), "places")
    aliases = list(adapter.names(raw, CONTEXT))
    assert [row["name_kind"] for row in aliases] == ["primary", "common", "historic"]
    assert aliases[-1]["is_historic"] is True
    assert aliases[0]["language"] is None
    assert aliases == list(adapter.names(raw, CONTEXT))
    validate_table(pa.Table.from_pylist(aliases, schema=SCHEMAS["names"]), "names")


def test_ascii_primary_is_not_assumed_english() -> None:
    raw = division()
    raw["names"] = {"primary": "ASCII name"}
    assert adapter.place(raw, CONTEXT)["name_en"] is None


def test_repair_split_flags_ids_and_containment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = area()
    raw["geometry"] = Polygon(
        [(-75, 40), (-73, 42), (-75, 42), (-73, 40), (-75, 40)]
    ).wkb
    stats: Counter[str] = Counter()
    spots: dict[str, list[dict[str, Any]]] = {label: [] for label in adapter.SPOTS}
    converted = list(adapter.areas(raw, CONTEXT, "parent-1", stats, spots))
    assert stats["invalid_input"] == stats["repaired_input"] == 1
    assert all(
        row["source_id"] == "area-1" and row["entity_id"] == "point-1"
        for row in converted
    )
    assert converted[0]["parent_source_id"] == "parent-1"
    assert converted[0]["is_land"] and converted[0]["is_territorial"]
    validate_table(pa.Table.from_pylist(converted, schema=SCHEMAS["areas"]), "areas")
    monkeypatch.setattr(adapter, "GEOMETRY_BYTES", 160)
    geometry = shapely.MultiPolygon([box(0, 0, 1, 1), box(2, 2, 3, 3)])
    parts = list(adapter.split_geometry(geometry))
    assert len(parts) == 2
    assert shapely.unary_union(parts).equals(geometry)


def _fixture(workspace: Workspace) -> None:
    workspace.prepare()
    objects: list[dict[str, Any]] = []
    for kind, rows in (
        ("division", [division(), division("point-2", "locality")]),
        ("division_area", [area()]),
    ):
        # Arrow maps are represented as key/value pairs on conversion to Python.
        for row in rows:
            row["names"]["common"] = {"en": "Test"}
        path = workspace.raw("overture") / f"test-1/{kind}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pylist(rows), path, row_group_size=1)
        write_json(
            path.with_name(path.name + ".download.json"),
            {"verified_sha256": sha256_file(path)},
        )
        objects.append(
            {
                "key": kind,
                "type": kind,
                "relative_path": f"test-1/{kind}.parquet",
                "url": "https://example.test/" + kind,
                "etag": '"test"',
                "size": path.stat().st_size,
            }
        )
    write_json(
        workspace.raw("overture") / "inventory.json",
        {"source_release": "test-1", "objects": objects, "retrieved_at": "2026-10-01"},
    )
    write_json(
        workspace.raw("overture") / "download-summary.json",
        {"source_release": "test-1", "rows": {"division": 2, "division_area": 1}},
    )


def test_normalize_resume_corruption_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    _fixture(workspace)
    adapter.run(workspace)
    normalized = workspace.normalized("overture")
    report = json.loads((normalized / "verification.json").read_text())
    assert report["rows"] == {"places": 2, "areas": 1, "names": 6}
    assert report["counts"].get("rejected_features", 0) == 0
    assert report["spot_checks"]["lower Manhattan"][0]["name"] == "Area"
    paths = list(normalized.rglob("*.parquet"))
    times = {path: path.stat().st_mtime_ns for path in paths}
    adapter.run(workspace)
    assert {path: path.stat().st_mtime_ns for path in paths} == times
    target = paths[0]
    expected = sha256_file(target)
    target.write_bytes(b"corrupt")
    adapter.run(workspace)
    assert sha256_file(target) == expected
    manifest = json.loads((normalized / "manifest.json").read_text())
    assert len(manifest["units"]) == 3
    assert all(entry["stage"] == "overture.normalize" for entry in manifest["units"])


def test_download_verified_files_are_reused_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from build_data.acquire import overture

    workspace = Workspace(tmp_path)
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    _fixture(workspace)
    inventory_path = workspace.raw("overture") / "inventory.json"
    inventory = json.loads(inventory_path.read_text())
    for obj in inventory["objects"]:
        obj["last_modified"] = None
        path = workspace.raw("overture") / obj["relative_path"]
        write_json(
            path.with_name(path.name + ".download.json"),
            {
                "url": obj["url"],
                "size": obj["size"],
                "etag": obj["etag"],
                "last_modified": None,
                "expected_sha256": None,
                "verified_sha256": sha256_file(path),
            },
        )
    write_json(inventory_path, inventory)
    overture.download(workspace)
    overture.download(workspace)
    summary = json.loads(
        (workspace.raw("overture") / "download-summary.json").read_text()
    )
    assert summary["rows"] == {"division": 2, "division_area": 1}


def test_rejects_account_for_every_source_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    _fixture(workspace)
    inventory_path = workspace.raw("overture") / "inventory.json"
    inventory = json.loads(inventory_path.read_text())
    obj = inventory["objects"][0]
    path = workspace.raw("overture") / obj["relative_path"]
    raw = pq.read_table(path).to_pylist()
    raw[1]["geometry"] = b"not WKB"
    pq.write_table(pa.Table.from_pylist(raw), path, row_group_size=1)
    obj["size"] = path.stat().st_size
    write_json(inventory_path, inventory)
    write_json(
        path.with_name(path.name + ".download.json"),
        {"verified_sha256": sha256_file(path)},
    )
    adapter.run(workspace)
    report = json.loads(
        (workspace.normalized("overture") / "verification.json").read_text()
    )
    assert report["rows"]["places"] == 1
    assert report["counts"]["input_rows"] == 3
    assert report["counts"]["accepted_features"] == 2
    assert report["counts"]["rejected_features"] == 1
    audits = [
        json.loads(path.read_text())
        for path in (workspace.normalized("overture") / "audits").rglob("*.json")
    ]
    rejects = [reject for audit in audits for reject in audit["rejects"]]
    assert rejects[0]["id"] == "point-2"
    assert rejects[0]["row_in_group"] == 0


def test_writer_failure_is_not_counted_as_a_rejected_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = Workspace(tmp_path)
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    _fixture(workspace)

    def fail(self: adapter.Sink, row: dict[str, Any]) -> None:
        raise ValueError("partition validation failed")

    monkeypatch.setattr(adapter.Sink, "add", fail)
    with pytest.raises(ValueError, match="partition validation failed"):
        adapter.run(workspace)
    assert not (workspace.normalized("overture") / "manifest.json").exists()


def test_corrupt_parent_index_is_rebuilt_from_verified_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = Workspace(tmp_path)
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    _fixture(workspace)
    adapter.run(workspace)
    path = workspace.work / "overture/entities.sqlite3"
    path.write_bytes(b"damaged index")
    adapter.run(workspace)
    import sqlite3

    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 2
