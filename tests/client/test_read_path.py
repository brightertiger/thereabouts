from pathlib import Path
from typing import Any

import numpy as np
import pytest
from h3.api import basic_int as h3

from thereabouts.client import Geocoder
from thereabouts.client_errors import InvalidInputError
from thereabouts.reading.places import retained_bytes

from .test_api import BRANCHES, PACK, finest


def test_decoded_places_are_lazy_reused_and_detached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Geocoder(PACK) as geo:
        assert geo.info()["cache"]["entries"] == 0
        first = geo.from_h3(finest(BRANCHES[0]))
        count = geo.info()["cache"]["misses"]

        def unexpected_record(reference: int) -> dict[str, Any]:
            pytest.fail(f"Decoded a cached place again: {reference}")

        monkeypatch.setattr(geo._pack, "record", unexpected_record)
        second = geo.from_h3(finest(BRANCHES[0]))
        assert first == second and first.selected and second.selected
        assert first.selected.city is second.selected.city
        assert count == geo.info()["cache"]["misses"]
    assert first.to_dict() == second.to_dict()


def test_cache_budget_eviction_and_disabled_parity() -> None:
    with Geocoder(PACK, cache_bytes=0) as uncached:
        expected = uncached.from_h3(finest(BRANCHES[0]))
        assert uncached.info()["cache"]["entries"] == 0
        entry = uncached._pack.places.get(1)
        assert entry is not None
        budget = retained_bytes(entry) * 2
    with Geocoder(PACK, cache_bytes=budget) as cached:
        for _ in range(3):
            assert cached.from_h3(finest(BRANCHES[0])) == expected
            info = cached.info()["cache"]
            assert info["retained_bytes"] <= budget
        assert info["evictions"] > 0 and info["entries"] > 0
    with Geocoder(PACK, cache_bytes=1) as tiny:
        assert tiny.from_h3(finest(BRANCHES[0])) == expected
        assert tiny.info()["cache"]["retained_bytes"] == 0
    for invalid in (-1, True, 1.5):
        with pytest.raises(InvalidInputError):
            Geocoder(PACK, cache_bytes=invalid)  # type: ignore[arg-type]


def test_columns_do_not_decode_and_objects_decode_only_when_requested() -> None:
    cells = [finest(BRANCHES[1]), finest(BRANCHES[0])]
    points = [h3.cell_to_latlng(int(cell, 16)) for cell in cells]
    with Geocoder(PACK) as geo:
        column = next(geo.reverse_columns(points))
        assert column.status.tolist() == ["unassigned", "matched"]
        assert geo.info()["cache"]["misses"] == 0
        answers = geo.reverse_many(points)
        assert next(answers).status == "unassigned"
        assert geo.info()["cache"]["misses"] == 0
        assert next(answers).status == "matched"
        assert geo.info()["cache"]["misses"] > 0


def test_numeric_input_types_and_column_stored_parent() -> None:
    cells = [finest(branch) for branch in BRANCHES]
    points = np.array([h3.cell_to_latlng(int(cell, 16)) for cell in cells])
    with Geocoder(PACK) as geo:
        columns = next(geo.reverse_columns(points))
        expected = list(geo.from_h3_many(cells))
        assert columns.stored_h3.tolist() == [
            int(answer.reference.stored_h3, 16)
            if answer.reference and answer.reference.stored_h3
            else 0
            for answer in expected
        ]
        bad = next(
            geo.reverse_columns([(np.bool_(True), 0), (0, "0")], errors="collect")
        )
        assert bad.status.tolist() == ["invalid_input", "invalid_input"]


def test_mixed_shards_stay_mapped_until_close(tmp_path: Path) -> None:
    from build_data.serve.export import export
    from tests.serve.fixtures import golden

    manifest, release = golden(tmp_path / "input")
    output = export(manifest, release, tmp_path / "pack", shard_bytes=256)
    geo = Geocoder(output)
    points = [(12.97, 77.59), (0, 179.99)]
    expected = [geo.reverse(*point) for point in points]
    mappings = dict(geo._pack.spatials)
    for _ in range(2):
        assert list(geo.reverse_many(points)) == expected
        assert geo._pack.spatials == mappings
    geo.close()
    assert not geo._pack.spatials and not geo._pack.catalogue_maps
    assert all(shard.data.closed for shard in mappings.values())
