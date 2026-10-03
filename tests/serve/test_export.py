import importlib
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from h3.api import basic_int as h3

from pipeline.engines.serving.checkpoints import file_record
from pipeline.engines.serving.export import export
from pipeline.engines.serving.metadata import write_manifest
from pipeline.engines.serving.snapshot import Row, read_snapshot
from thereabouts.packs.address import address, cell_at
from thereabouts.packs.catalogue import Catalogue
from thereabouts.packs.jsonio import parse, sha256
from thereabouts.packs.layout import CITY_METHODS
from thereabouts.packs.spatial import Spatial
from thereabouts.packs.verify import verify


def contents(path: Path) -> dict[str, tuple[str, int]]:
    return {
        p.relative_to(path).as_posix(): (sha256(p), p.stat().st_mtime_ns)
        for p in path.rglob("*")
        if p.is_file()
    }


def test_export_preserves_every_ancestor_and_minimal_closure(
    serving: Path, snapshot: tuple[Path, Path]
) -> None:
    manifest = verify(serving)
    assert (
        manifest["place_count"] == 5
    )  # unused city omitted; district/sovereign retained
    assert manifest["coverage"] == "blocks"
    source = read_snapshot(snapshot[0])
    records = {}
    for r in manifest["files"]:
        if r["kind"] != "catalogue":
            continue
        catalogue = Catalogue(serving / r["path"], manifest["place_count"])
        try:
            for i in range(r["count"]):
                records[r["first_id"] + i] = catalogue.record(i)
        finally:
            catalogue.close()
    assert len(records) == 5
    city = next(r for r in records.values() if r["role"] == "city")
    assert records[city["parent_id"]]["role"] == "district"
    assert records[city["sovereign_id"]]["place_id"] == "country:BB"
    assert city["name_en"] is None and city["local_name"] == "東京"
    assert city["evidence"]["source_ids"] == [{"source": "synthetic", "id": "a"}]
    seen = set()
    for shard in manifest["files"]:
        if shard["kind"] != "cells":
            continue
        spatial = Spatial(serving / shard["path"], manifest["place_count"])
        try:
            for table in source.tables("cells"):
                block = address(int(table["block"], 16), 3)[0]
                if block not in spatial.blocks:
                    continue
                expected = pq.ParquetFile(source.file(table)).read().to_pylist()
                assert len(expected) == spatial.blocks[block].count
                # Exhaust every actual r8 descendant, including absence and pentagons.
                by_cell = {r["h3_uint64"]: r for r in expected}
                for fine in h3.cell_to_children(int(table["block"], 16), 8):
                    match = next(
                        (
                            by_cell[a]
                            for level in range(8, 2, -1)
                            if (a := h3.cell_to_parent(fine, level)) in by_cell
                        ),
                        None,
                    )
                    actual = spatial.lookup(*address(fine, 8))
                    if match is None:
                        assert actual is None
                        continue
                    assert actual is not None
                    key, label = actual
                    assert cell_at(block, key) == match["h3_uint64"]
                    for ref, field in zip(
                        label[:3], ("country_id", "state_id", "city_id"), strict=True
                    ):
                        assert (records[ref]["place_id"] if ref else None) == match[
                            field
                        ]
                    assert CITY_METHODS[label[3] & 7] == match["city_method"]
                    assert bool(label[3] & 32) == (match["land_method"] == "offshore")
                    seen.add(match["city_method"])
        finally:
            spatial.close()
    assert seen == set(CITY_METHODS)


def test_idempotent_portable_and_deterministic(
    snapshot: tuple[Path, Path], tmp_path: Path
) -> None:
    output = export(*snapshot, tmp_path / "one", shard_bytes=1024)
    before = contents(output)
    export(*snapshot, output, shard_bytes=1024)
    assert contents(output) == before
    moved = tmp_path / "relocated"
    shutil.copytree(snapshot[1].parent, moved)
    other = export(
        moved / "golden/manifest.json",
        moved / "release.json",
        tmp_path / "two",
        shard_bytes=1024,
    )
    assert {k: v[0] for k, v in before.items()} == {
        k: v[0] for k, v in contents(other).items()
    }
    assert str(tmp_path) not in (output / "manifest.json").read_text()
    with pytest.raises(FileExistsError, match="different inputs"):
        export(*snapshot, output, shard_bytes=2048)


def test_resume_reuses_complete_units(
    snapshot: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = importlib.import_module("pipeline.engines.serving.export")
    original = module.write_cells
    calls = 0

    def interrupted(
        snapshot: object, tables: object, catalogue: object, path: Path
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk interruption")
        original(snapshot, tables, catalogue, path)

    monkeypatch.setattr(module, "write_cells", interrupted)
    output = tmp_path / "pack"
    with pytest.raises(OSError, match="interruption"):
        export(*snapshot, output, shard_bytes=1024)
    assert not output.exists()
    work = next(tmp_path.glob(".serve-*/pack"))
    completed = work / "cells-00000.bin"
    stamp = completed.stat().st_mtime_ns
    monkeypatch.setattr(module, "write_cells", original)
    export(*snapshot, output, shard_bytes=1024)
    assert (output / completed.name).stat().st_mtime_ns == stamp
    verify(output)
    assert not list(tmp_path.glob(".serve-*"))


@pytest.mark.parametrize(
    "field,value",
    [("completed", False), ("schema_version", "golden-1"), ("reference_resolution", 7)],
)
def test_reject_unverified_generation(
    snapshot: tuple[Path, Path], tmp_path: Path, field: str, value: object
) -> None:
    data = parse(snapshot[0].read_bytes())
    data[field] = value
    write_manifest(snapshot[0], data)
    with pytest.raises(ValueError):
        export(*snapshot, tmp_path / "no-pack")
    assert not (tmp_path / "no-pack").exists()


def test_reject_corrupt_source_and_quality(
    snapshot: tuple[Path, Path], tmp_path: Path
) -> None:
    data = parse(snapshot[0].read_bytes())
    root = snapshot[1].parent
    record: Row = data["verification_artifacts"][0]
    path = root / record["path"]
    path.write_text("corrupt")
    with pytest.raises(ValueError, match="artifact"):
        export(*snapshot, tmp_path / "no-pack")
    quality = {"integrity": {"duplicate_place_ids": 1}}
    write_manifest(path, quality)
    data["verification_artifacts"][0] = file_record(path, root)
    write_manifest(snapshot[0], data)
    with pytest.raises(ValueError, match="integrity"):
        export(*snapshot, tmp_path / "no-pack")
