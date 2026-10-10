"""Table zips are deterministic, exact in size, split under the cap and readable."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from pipeline.release import dataset_zips
from pipeline.release.dataset_zips import Member, build, plan
from thereabouts import _core

FILES = {
    "cells/group=81653ffffffffff/part.parquet": b"cells " * 100,
    "cells/group=8165bffffffffff/part.parquet": b"more cells " * 60,
    "places/country=MY/part.parquet": b"places",
    "names/part.parquet": b"",
}


def dataset(root: Path) -> list[Member]:
    members = []
    for path, data in FILES.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        members.append(Member(path, len(data), hashlib.sha256(data).hexdigest()))
    return members


def test_one_zip_per_table_rebuilds_the_tree(tmp_path: Path) -> None:
    members = dataset(tmp_path / "dataset")
    zips = plan(members, 2**31 - 1)
    assert [(z.name, z.table) for z in zips] == [
        ("dataset-cells.zip", "cells"),
        ("dataset-names.zip", "names"),
        ("dataset-places.zip", "places"),
    ]
    written = build(zips, tmp_path / "dataset", tmp_path / "out")
    for item in zips:
        path = written[item.name]
        assert path.stat().st_size == item.size
        summary = _core.inspect_zip(str(path))
        assert summary["unpacked_size"] == item.unpacked_size
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            for info in archive.infolist():
                assert archive.read(info) == FILES[info.filename]
                assert info.date_time == (1980, 1, 1, 0, 0, 0)
                assert info.compress_type == zipfile.ZIP_STORED and not info.extra


def test_zips_are_byte_identical_on_rewrite_and_reused(tmp_path: Path) -> None:
    members = dataset(tmp_path / "dataset")
    zips = plan(members, 2**31 - 1)
    first = build(zips, tmp_path / "dataset", tmp_path / "a")
    second = build(zips, tmp_path / "dataset", tmp_path / "b")
    for name, path in first.items():
        assert path.read_bytes() == second[name].read_bytes()
    stamp = first["dataset-cells.zip"].stat().st_mtime_ns
    build(zips, tmp_path / "dataset", tmp_path / "a")
    assert first["dataset-cells.zip"].stat().st_mtime_ns == stamp


def test_a_large_table_splits_under_the_asset_cap(tmp_path: Path) -> None:
    members = dataset(tmp_path / "dataset")
    cap = 1500
    zips = plan(members, cap)
    cells = [z for z in zips if z.table == "cells"]
    assert [z.name for z in cells] == ["dataset-cells-001.zip", "dataset-cells-002.zip"]
    assert all(z.size <= cap for z in zips)
    written = build(zips, tmp_path / "dataset", tmp_path / "out")
    found = sorted(
        row["path"]
        for z in cells
        for row in _core.inspect_zip(str(written[z.name]))["files"]
    )
    assert found == sorted(p for p in FILES if p.startswith("cells/"))


def test_files_that_cannot_ship_are_refused(tmp_path: Path) -> None:
    members = dataset(tmp_path / "dataset")
    with pytest.raises(ValueError, match="exceeds one release asset"):
        plan(members, 700)
    with pytest.raises(ValueError, match="Only table files"):
        plan([Member("README.md", 1, "0" * 64)], 2**31 - 1)
    with pytest.raises(ValueError, match="asset name"):
        plan([Member("bad table/x", 1, "0" * 64)], 2**31 - 1)


def test_a_changed_input_never_leaves_a_zip(tmp_path: Path) -> None:
    members = dataset(tmp_path / "dataset")
    zips = plan(members, 2**31 - 1)
    (tmp_path / "dataset/names/part.parquet").write_bytes(b"x")
    with pytest.raises(ValueError, match="changed while zipping"):
        build(zips, tmp_path / "dataset", tmp_path / "out")
    assert not (tmp_path / "out/dataset-names.zip").exists()


def test_a_tampered_zip_on_disk_is_refused(tmp_path: Path) -> None:
    members = dataset(tmp_path / "dataset")
    zips = plan(members, 2**31 - 1)
    written = build(zips, tmp_path / "dataset", tmp_path / "out")
    path = written["dataset-places.zip"]
    data = bytearray(path.read_bytes())
    data[dataset_zips.LOCAL_BYTES + len("places/country=MY/part.parquet")] ^= 1
    path.write_bytes(bytes(data))
    with pytest.raises(ValueError, match="refused by the reader"):
        build(zips, tmp_path / "dataset", tmp_path / "out")
