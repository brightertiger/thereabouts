"""Production block expansion and resumable recompaction on tiny source inputs."""

from pathlib import Path

import pytest
import shapely

from tests.test_city_normalization import city, make_engine


def test_compact_parent_splits_at_new_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import h3

    from pipeline.engines.cells.reader import Cells
    from pipeline.engines.cells.schemas import CELLS
    from pipeline.engines.normalize_cells.blocks import transform
    from pipeline.engines.storage import parquet

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
        tmp_path,
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
        1024,
    )
    base.update(kind="cells", block=root)
    base["path"] = str(tmp_path / base["path"])
    rows, _ = transform(base, {"ZZ": engine}, False)
    table = parquet(tmp_path, tmp_path / "normalized.parquet", rows, CELLS, 1024)
    table.update(kind="cells", block=root, path=str(tmp_path / table["path"]))
    assert table["rows"] > 1
    reader = Cells([table])
    for cell in h3.cell_to_children(root, 8):
        y, x = h3.cell_to_latlng(cell)
        expected = "town" if shape.covers(shapely.Point(x, y)) else "village"
        assert reader.lookup(cell)["city_id"] == expected


def test_empty_ocean_block_does_not_enumerate_centres(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.engines.cells.schemas import CELLS
    from pipeline.engines.normalize_cells.blocks import transform
    from pipeline.engines.storage import parquet

    def unexpected_enumeration(*args: object) -> None:
        raise AssertionError("An empty base block has no eligible centres")

    record = parquet(tmp_path, tmp_path / "ocean.parquet", [], CELLS, 1024)
    record["path"] = str(tmp_path / record["path"])
    monkeypatch.setattr(
        "pipeline.engines.normalize_cells.blocks.descendants", unexpected_enumeration
    )
    assert transform(record, {}, False) == ([], {})
