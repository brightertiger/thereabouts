from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from threading import Event

import numpy as np
import pytest
from h3.api import basic_int as h3

from thereabouts.client import Geocoder
from thereabouts.client_errors import InvalidInputError
from thereabouts.errors import ClosedGeocoderError
from thereabouts.reading.inputs import coordinates

from .test_api import BRANCHES, PACK, ROOT, finest


def test_scalar_batch_parity_all_ancestors_and_order() -> None:
    roots = [ROOT, h3.get_pentagons(3)[0], h3.latlng_to_cell(-89.99, 0, 3)]
    cells = [child for root in roots for child in h3.cell_to_children(root, 8)]
    with Geocoder(PACK) as geo:
        # Exhaust all r8 keys against the independent scalar binary search.
        for root in roots:
            from thereabouts.packs.address import address

            block, _ = address(root, 3)
            shard = geo._pack.spatial_for(block)
            assert shard is not None
            children = h3.cell_to_children(root, 8)
            keys = [address(cell, 8)[1] for cell in children]
            index = geo._pack.index_for(block)
            assert index is not None
            stored, labels = index.lookup_many(
                np.full(len(keys), block, dtype=np.int64),
                np.array(keys, dtype=np.int64),
            )
            expected = [shard.lookup(block, key) for key in keys]
            actual = [
                None if key < 0 else (int(key), tuple(map(int, label)))
                for key, label in zip(stored, labels, strict=True)
            ]
            assert actual == expected
        # Public decoding, mixed blocks, duplicates, reversed order and partial chunks.
        chosen = [str(h3.int_to_str(cell)) for cell in cells[::211]][::-1]
        chosen += [finest(BRANCHES[1]), chosen[0], finest(BRANCHES[6])]
        assert list(geo.from_h3_many(chosen, chunk_size=19)) == [
            geo.from_h3(c) for c in chosen
        ]
        points = [h3.cell_to_latlng(int(cell, 16)) for cell in chosen]
        assert list(geo.reverse_many(points, chunk_size=23)) == [
            geo.reverse(*p) for p in points
        ]


def test_collection_is_bounded_and_only_collects_invalid_rows() -> None:
    consumed = []

    def source() -> Iterator[object]:
        for index, value in enumerate([(12, 77), None, (0, 180), (True, 4), (0, 0)]):
            consumed.append(index)
            yield value

    with Geocoder(PACK) as geo:
        batch = geo.reverse_many(source(), chunk_size=2, errors="collect")
        assert next(batch).status != "invalid_input"
        assert consumed == [0, 1]
        assert next(batch).status == "invalid_input"
        tail = list(batch)
        assert [r.status for r in tail] == [
            "ineligible",
            "invalid_input",
            "outside_coverage",
        ]
        batch = geo.reverse_many([(0, 0), (91, 0)], chunk_size=1)
        assert next(batch).status == "outside_coverage"
        with pytest.raises(InvalidInputError):
            next(batch)
        assert list(geo.reverse_many([])) == []
        for size in [True, 0, -1]:
            with pytest.raises(InvalidInputError):
                geo.reverse_many([], chunk_size=size)
        with pytest.raises(InvalidInputError):
            geo.reverse_many([], errors="ignore")  # type: ignore[arg-type]


def test_columns_and_decoding_own_their_data() -> None:
    points = [h3.cell_to_latlng(int(finest(branch), 16)) for branch in BRANCHES]
    geo = Geocoder(PACK)
    expected = list(geo.reverse_many(points))
    result = next(geo.reverse_columns(points, decode=True))
    numeric = next(geo.reverse_columns([None, *points], errors="collect"))
    geo.close()
    assert result.status.tolist() == [r.status for r in expected]
    assert result.h3.tolist() == [coordinates(p)[0] for p in points]
    assert numeric.valid.tolist() == [False] + [True] * len(points)
    assert numeric.places is None and numeric.errors[0]
    assert numeric.present.tolist()[1:] == [
        r.reference.stored_h3 is not None for r in expected if r.reference
    ]
    assert result.city_ref.dtype == np.dtype("uint32") and result.places
    city = result.places[int(result.city_ref[0])]
    assert city.id == "city:synthetic:A"
    assert result.country_ref[1] == result.city_ref[1] == 0
    assert result.present[1] and not result.present[6]
    with pytest.raises(ValueError):
        result.h3[0] = 0


def test_close_invalidates_calls_and_buffered_iterators() -> None:
    geo = Geocoder(PACK)
    batch = geo.reverse_many([(0, 0)] * 3)
    columns = geo.reverse_columns([(0, 0)] * 3, chunk_size=1)
    next(batch)
    next(columns)
    geo.close()
    geo.close()
    calls: list[Callable[[], object]] = [
        lambda: next(batch),
        lambda: next(columns),
        geo.info,
        lambda: geo.reverse(0, 0),
        lambda: geo.from_h3(finest(ROOT)),
        lambda: geo.reverse_many([]),
        lambda: geo.__enter__(),
    ]
    for call in calls:
        with pytest.raises(ClosedGeocoderError):
            call()


def test_concurrent_reads_and_close_waits_for_active_chunk() -> None:
    geo = Geocoder(PACK)
    with ThreadPoolExecutor(max_workers=3) as pool:
        cells = [finest(branch) for branch in BRANCHES] * 3
        assert list(pool.map(geo.from_h3, cells)) == [geo.from_h3(c) for c in cells]
        entered, release, closing = Event(), Event(), Event()

        def source() -> Iterator[object]:
            entered.set()
            assert release.wait(5)
            yield (0, 0)

        future = pool.submit(lambda: next(geo.reverse_many(source())))
        assert entered.wait(5)

        def close() -> None:
            closing.set()
            geo.close()

        closer = pool.submit(close)
        assert closing.wait(5) and not closer.done()
        release.set()
        # Close may linearize before the first buffered result is handed back.
        with suppress(ClosedGeocoderError):
            future.result()
        closer.result()
    with pytest.raises(ClosedGeocoderError):
        geo.info()


@pytest.mark.parametrize("columns", [False, True])
def test_source_iterator_can_close_without_reopening_mappings(columns: bool) -> None:
    geo = Geocoder(PACK)

    def source() -> Iterator[object]:
        yield (12.97, 77.59)
        geo.close()

    iterator = geo.reverse_columns(source()) if columns else geo.reverse_many(source())
    with pytest.raises(ClosedGeocoderError):
        next(iterator)
    assert not geo._pack.spatials and not geo._pack.catalogue_maps


def test_numeric_input_callback_cannot_reopen_closed_reader() -> None:
    geo = Geocoder(PACK)

    class ClosingFloat(float):
        def __float__(self) -> float:
            geo.close()
            return super().__float__()

    with pytest.raises(ClosedGeocoderError):
        next(geo.reverse_many([(ClosingFloat(12.97), 77.59)]))
    assert not geo._pack.spatials
