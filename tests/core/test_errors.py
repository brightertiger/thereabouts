"""Configuration, data corruption and writer failures retain distinct codes."""

from pathlib import Path

import pytest

from thereabouts import (
    CorruptPackError,
    Geocoder,
    PackNotFoundError,
    WriterInputError,
    _core,
)

DATASET = Path(__file__).parents[1] / "fixtures/datasets/core-synthetic/golden"


def test_missing_explicit_path_is_not_missing_store_data(tmp_path: Path) -> None:
    path = tmp_path / "absent"
    with pytest.raises(PackNotFoundError) as caught:
        Geocoder(path)
    assert caught.value.code == "pack_not_found"
    assert str(path) in str(caught.value)
    path.mkdir()
    with pytest.raises(CorruptPackError) as corrupt:
        Geocoder(path)
    assert corrupt.value.code == "corrupt_pack"


def test_writer_options_and_stale_staging_have_actionable_errors(
    tmp_path: Path,
) -> None:
    with pytest.raises(WriterInputError) as options:
        _core.write_pack(str(DATASET), "core", str(tmp_path / "pack"), {})
    assert isinstance(options.value, ValueError)
    assert options.value.code == "writer_input_error"
    stale = tmp_path / ".pack.building"
    stale.mkdir()
    marker = stale / "keep"
    marker.write_text("unrelated interrupted build")
    with pytest.raises(WriterInputError) as caught:
        _core.write_pack(
            str(DATASET), "core", str(tmp_path / "pack"), {"data_version": "test"}
        )
    assert f"remove {stale} and retry" in str(caught.value)
    assert marker.read_text() == "unrelated interrupted build"
