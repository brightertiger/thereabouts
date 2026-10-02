"""Production block expansion and resumable recompaction on tiny source inputs."""

from pathlib import Path

import pytest
import shapely

from tests.test_city_normalization import city, make_engine


def test_compact_parent_splits_at_new_boundary_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("build_data.normalize_cells.blocks.budget", lambda _: None)
    import h3

    from build_data.acquire import Workspace
    from build_data.golden.reader import Cells
    from build_data.golden.schemas import CELLS
    from build_data.golden.storage import parquet
    from build_data.normalize_cells.blocks import build

    shape = shapely.box(-0.1, -2, 0.1, 2)
    engine = make_engine(
        tmp_path,
        [city("town", 0, 10000)],
        [
            {
                "city_id": "town",
                "priority": 0,
                "method": "city_polygon",
                "geometry": shape,
            }
        ],
    )
    root = h3.latlng_to_cell(0, 0, 3)
    base = parquet(
        tmp_path / "base.parquet",
        [
            {
                "h3": root,
                "h3_uint64": int(root, 16),
                "h3_resolution": 3,
                "country_id": "country:ZZ",
                "state_id": None,
                "city_id": "village",
                "country_method": "area",
                "state_method": None,
                "city_method": "area",
                "land_method": "land",
            }
        ],
        CELLS,
    )
    base.update(kind="cells", block=root)
    workspace = Workspace(tmp_path)
    output = tmp_path / "v2"
    result = build(workspace, output, base, {"ZZ": engine}, "version-one", False)
    table = result["table"]
    assert table["rows"] > 1
    reader = Cells([table])
    for cell in h3.cell_to_children(root, 8):
        y, x = h3.cell_to_latlng(cell)
        expected = "town" if shape.covers(shapely.Point(x, y)) else "village"
        assert reader.lookup(cell)["city_id"] == expected
    modified = Path(table["path"]).stat().st_mtime_ns
    assert (
        build(workspace, output, base, {"ZZ": engine}, "version-one", False) == result
    )
    assert Path(table["path"]).stat().st_mtime_ns == modified
    Path(table["path"]).write_bytes(b"interrupted/corrupt artifact")
    repaired = build(workspace, output, base, {"ZZ": engine}, "version-one", False)
    assert repaired["table"]["sha256"] == table["sha256"]
    # The actual block key and receipt must also survive relocating the data root.
    relocated = tmp_path.with_name(tmp_path.name + "-moved")
    tmp_path.rename(relocated)
    base = {**base, "path": str(relocated / "base.parquet")}

    def unexpected_rebuild(*args: object) -> None:
        raise AssertionError("Moving a completed block must not transform it again")

    monkeypatch.setattr(
        "build_data.normalize_cells.blocks.transform", unexpected_rebuild
    )
    resumed = build(
        Workspace(relocated), relocated / "v2", base, {}, "version-one", False
    )
    assert resumed["table"]["sha256"] == repaired["table"]["sha256"]
    assert Path(resumed["table"]["path"]).is_relative_to(relocated)
    assert Path(resumed["table"]["path"]).is_file()


def test_empty_ocean_block_does_not_enumerate_centres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from build_data.golden.schemas import CELLS
    from build_data.golden.storage import parquet
    from build_data.normalize_cells.blocks import transform

    def unexpected_enumeration(*args: object) -> None:
        raise AssertionError("An empty base block has no eligible centres")

    record = parquet(tmp_path / "ocean.parquet", [], CELLS)
    monkeypatch.setattr(
        "build_data.normalize_cells.blocks.descendants", unexpected_enumeration
    )
    assert transform(record, {}, False) == ([], {})
