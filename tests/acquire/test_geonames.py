"""Synthetic GeoNames snapshots, interruption recovery and broad normalization."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from build_data.acquire import Workspace, sha256_file, validate_parquet, write_partition
from build_data.acquire import geonames_download as downloads
from build_data.acquire import geonames_normalize as normalizer
from build_data.acquire import geonames_statistics as statistics
from build_data.acquire.download import RemoteChangedError
from build_data.acquire.geonames_rows import alias, english_rank, place
from build_data.acquire.io import write_json
from build_data.acquire.schemas import Kind

PIN: dict[str, object] = {
    "url": "https://example.invalid/geonames.zip",
    "sha256": "0" * 64,
    "retrieved_at": "2026-10-01",
    "last_modified": "2026-10-01",
}


def feature(
    identifier: int,
    code: str = "PPL",
    feature_class: str = "P",
    name: str = "Cafe\u0301",
    population: str = "0",
) -> bytes:
    return (
        "\t".join(
            [
                str(identifier),
                name,
                "Cafe",
                "Coffee,Café",
                "1.5",
                "2.5",
                feature_class,
                code,
                "US",
                "CA",
                "01",
                "002",
                "003",
                "004",
                population,
                "42",
                "45",
                "America/New_York",
                "2026-10-01",
            ]
        )
        + "\n"
    ).encode()


def alternate(
    identifier: int,
    entity: int,
    language: str = "en",
    name: str = "Coffee",
    flags: tuple[str, ...] = ("1", "", "", ""),
    start: str = "",
    end: str = "",
) -> bytes:
    return (
        "\t".join([str(identifier), str(entity), language, name, *flags, start, end])
        + "\n"
    ).encode()


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    workspace = Workspace(tmp_path / "data")
    workspace.prepare()
    monkeypatch.setattr(normalizer, "CHUNK_BYTES", 200)
    monkeypatch.setattr(normalizer, "BATCH_ROWS", 2)
    monkeypatch.setattr(normalizer, "PARTITION_BYTES", 3000)
    return workspace


def snapshot(workspace: Workspace, features: bytes, aliases: bytes) -> None:
    root = workspace.raw("geonames")
    files: dict[str, dict[str, object]] = {}
    for archive, member, content in (
        ("allCountries.zip", "allCountries.txt", features),
        ("alternateNamesV2.zip", "alternateNamesV2.txt", aliases),
    ):
        with zipfile.ZipFile(root / archive, "w", zipfile.ZIP_DEFLATED) as zipped:
            zipped.writestr(member, content)
            if archive == "alternateNamesV2.zip":
                zipped.writestr("iso-languagecodes.txt", "en\tEnglish\n")
    for name in downloads.FILES:
        path = root / name
        if not path.exists():
            path.write_text("#synthetic support table\n", encoding="utf-8")
        files[name] = {
            **PIN,
            "path": str(path),
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }
    write_json(
        root / "inventory.json",
        {
            "source": "geonames",
            "source_release": "synthetic",
            "files": files,
            "completed_at": "2026-10-01",
        },
    )


def rows(workspace: Workspace, kind: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in workspace.normalized("geonames").joinpath(kind).rglob("*.parquet"):
        validate_parquet(path, cast(Kind, kind))
        result.extend(pq.ParquetFile(path).read().to_pylist())
    return result


def test_broad_rows_and_flags() -> None:
    for code in ("PPL", "PPLX", "PPLH", "PPLQ", "PPLW"):
        row = place(feature(1, code), "test", PIN)
        assert row is not None and row["feature_code"] == code
        assert row["population"] == 0 and row["name"] == "Café"
        assert row["name_en"] is None
        provenance = json.loads(str(row["provenance"]))
        assert provenance["admin3_code"] == "003"
        assert provenance["admin4_code"] == "004"
    for code in ("ADM1", "ADM4", "ADM5", "PCLI", "PCLD", "ADMH"):
        row = place(feature(2, code, "A"), "test", PIN)
        assert row is not None and row["kind"] == "administrative"
    assert place(feature(3, "MT", "T"), "test", PIN) is None
    row = alias(
        alternate(
            2, 1, "link", "https://example.org", ("1", "1", "1", "1"), "1700", "1800"
        ),
        "test",
        PIN,
    )
    assert all(
        row[key] for key in ("is_preferred", "is_short", "is_colloquial", "is_historic")
    )
    assert row["valid_from"] == "1700" and row["valid_to"] == "1800"
    assert english_rank(row) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"bad\n",
        feature(1).replace(b"1.5", b"nan"),
        feature(1, population="-1"),
        feature(0),
    ],
)
def test_invalid_points_are_explicit(raw: bytes) -> None:
    with pytest.raises(ValueError):
        place(raw, "test", PIN)


def test_end_to_end_rejects_counts_english_and_resume(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot(
        workspace,
        feature(1)
        + feature(2, "PPLH")
        + feature(3, "ADM4", "A")
        + feature(4, "MT", "T")
        + feature(1)
        + b"malformed\n",
        alternate(10, 1, name="Current English")
        + alternate(11, 1, name="Old English", flags=("1", "", "", "1"))
        + alternate(12, 2, "zh", "城市")
        + alternate(13, 3, "link", "https://a.test")
        + alternate(14, 4)
        + alternate(15, 999)
        + alternate(10, 1)
        + b"malformed\n",
    )
    normalizer.normalize(workspace)
    points, names = rows(workspace, "places"), rows(workspace, "names")
    assert len(points) == 3 and len(names) == 4
    assert (
        next(row for row in points if row["source_id"] == "1")["name_en"]
        == "Current English"
    )
    assert {row["source_id"] for row in names} == {"10", "11", "12", "13"}
    manifest_path = workspace.normalized("geonames") / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    counts = manifest["verification"]["counts"]
    assert counts["places"]["input"] == 6
    assert counts["places"]["rejected"] == 2 and counts["places"]["excluded"] == 1
    assert counts["names"]["input"] == 8
    assert counts["names"]["rejected"] == 2 and counts["names"]["excluded"] == 2
    parquet = sorted(workspace.normalized("geonames").rglob("*.parquet"))
    mtimes = {p: p.stat().st_mtime_ns for p in parquet}

    def no_work(*args: object, **kwargs: object) -> None:
        raise AssertionError("Completed units must not be transformed again")

    monkeypatch.setattr(normalizer, "write_partition", no_work)
    normalizer.normalize(workspace)
    assert {p: p.stat().st_mtime_ns for p in parquet} == mtimes
    monkeypatch.undo()


def test_resume_index_after_interruption(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot(workspace, b"".join(feature(i) for i in range(1, 12)), alternate(1, 1))
    original = normalizer._index_place
    calls = 0

    def interrupted(
        db: sqlite3.Connection,
        raw: bytes,
        offset: int,
        release: str,
        pin: dict[str, object],
    ) -> str:
        nonlocal calls
        calls += 1
        if calls == 7:
            raise RuntimeError("simulated interruption")
        return original(db, raw, offset, release, pin)

    monkeypatch.setattr(normalizer, "_index_place", interrupted)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        normalizer.normalize(workspace)
    monkeypatch.setattr(normalizer, "_index_place", original)
    normalizer.normalize(workspace)
    assert len(rows(workspace, "places")) == 11


def test_changed_validator_restarts_cleanly(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []
    probes = iter(['"old"', '"new"'])
    monkeypatch.setattr(downloads, "FILES", ("readme.txt",))
    monkeypatch.setattr(statistics, "download_statistics", lambda workspace: None)
    monkeypatch.setattr(
        downloads,
        "probe",
        lambda url: {
            "url": url,
            "size": 3,
            "etag": next(probes),
            "last_modified": None,
            "retrieved_at": "today",
        },
    )

    def transfer(url: str, destination: Path, **kwargs: object) -> Path:
        calls.append(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if len(calls) == 1:
            destination.with_name(destination.name + ".part").write_bytes(b"x")
            raise RemoteChangedError("daily rollover")
        destination.write_bytes(b"abc")
        destination.with_name(destination.name + ".download.json").write_text("{}")
        return destination

    monkeypatch.setattr(downloads, "download_file", transfer)
    downloads.download(workspace)
    assert calls[0] != calls[1]
    assert not calls[0].with_name("readme.txt.part").exists()
    inventory_path = workspace.raw("geonames") / "inventory.json"
    first = inventory_path.read_bytes()
    downloads.download(workspace)
    assert len(calls) == 2 and inventory_path.read_bytes() == first
    inventory = json.loads(first)
    assert inventory["files"]["readme.txt"]["etag"] == '"new"'
    assert len(inventory["superseded"]) == 1


def test_corrupt_input_is_never_published(workspace: Workspace) -> None:
    snapshot(workspace, feature(1), alternate(1, 1))
    (workspace.raw("geonames") / "allCountries.zip").write_bytes(b"broken")
    with pytest.raises(ValueError, match="checksum mismatch"):
        normalizer.normalize(workspace)
    assert not (workspace.normalized("geonames") / "manifest.json").exists()


def test_publisher_statistics_parser() -> None:
    html = "<table><tr><td>1,200</td><td><a>P.PPL</a></td></tr>"
    html += "<tr><td>1,300</td><td>Total for P</td></tr>"
    html += "<tr><td>23</td><td>Total for A</td></tr></table>"
    assert statistics.parse_counts(html) == {"P.PPL": 1200, "P": 1300, "A": 23}


def test_corrupt_partition_rebuilds_only_its_unit(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot(workspace, b"".join(feature(i) for i in range(1, 8)), alternate(1, 1))
    normalizer.normalize(workspace)
    partitions = sorted(workspace.normalized("geonames").rglob("*.parquet"))
    mtimes = {path: path.stat().st_mtime_ns for path in partitions}
    broken = partitions[0]
    broken.write_bytes(b"corrupt")
    replaced: list[Path] = []

    def tracked(
        path: Path, kind: Kind, batches: Iterable[pa.Table | pa.RecordBatch]
    ) -> None:
        replaced.append(path)
        write_partition(path, kind, batches)

    monkeypatch.setattr(normalizer, "write_partition", tracked)
    normalizer.normalize(workspace)
    assert broken in replaced
    for path in set(partitions) - set(replaced):
        assert path.stat().st_mtime_ns == mtimes[path]
    assert len(rows(workspace, "places")) == 7


def test_publication_failure_leaves_no_manifest(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot(workspace, feature(1), alternate(1, 1))

    def failure(*args: object, **kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(normalizer, "write_partition", failure)
    with pytest.raises(OSError, match="simulated disk failure"):
        normalizer.normalize(workspace)
    assert not (workspace.normalized("geonames") / "manifest.json").exists()
