import importlib
from collections.abc import Callable

import numpy as np
import pytest
from h3.api import basic_int as h3

from thereabouts.client import Geocoder
from thereabouts.client_errors import InvalidInputError
from thereabouts.packs.address import address, cell_at

from .test_api import BRANCHES, PACK, ROOT, finest


def native() -> Callable[[int, int], int]:
    module = pytest.importorskip("thereabouts.reading._reader_cy")
    return module.stored_cell  # type: ignore[no-any-return]


def test_numeric_kernel_exhausts_ordinary_and_pentagon_slots() -> None:
    kernel = native()
    for root in (ROOT, h3.get_pentagons(3)[0], h3.latlng_to_cell(-89.99, 0, 3)):
        block, _ = address(root, 3)
        for key in range(19608):
            try:
                expected = cell_at(block, key)
            except ValueError:
                with pytest.raises(ValueError):
                    kernel(block, key)
            else:
                assert kernel(block, key) == expected
    for block, key in [(-1, 0), (41846, 0), (0, -1), (0, 19608), (10**50, 0)]:
        with pytest.raises(ValueError):
            kernel(block, key)


def test_public_scalar_batch_columns_native_parity() -> None:
    native()
    cells = [finest(branch) for branch in BRANCHES]
    cells += [h3.int_to_str(c) for c in h3.cell_to_children(ROOT, 8)[::137]]
    with Geocoder(PACK) as compiled, Geocoder(PACK, backend="python") as reference:
        assert compiled.info()["backend"] == "cython"
        assert reference.info()["backend"] == "python"
        assert [compiled.from_h3(c) for c in cells] == [
            reference.from_h3(c) for c in cells
        ]
        assert list(compiled.from_h3_many(cells)) == list(reference.from_h3_many(cells))
        points = [h3.cell_to_latlng(int(cell, 16)) for cell in cells]
        left = next(compiled.reverse_columns(points, decode=True))
        right = next(reference.reverse_columns(points, decode=True))
        for field in (
            "h3",
            "stored_h3",
            "valid",
            "present",
            "status",
            "city_ref",
            "state_ref",
            "country_ref",
            "flags",
        ):
            np.testing.assert_array_equal(getattr(left, field), getattr(right, field))
        assert left.places == right.places and left.data == right.data


def test_missing_extension_falls_back_but_broken_import_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> None:
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(importlib, "import_module", missing)
    with Geocoder(PACK) as geo:
        assert geo.info()["backend"] == "python"
        assert geo.from_h3(finest(BRANCHES[0])).selected is not None

    def dependency(name: str) -> None:
        raise ModuleNotFoundError(name="missing_native_dependency")

    monkeypatch.setattr(importlib, "import_module", dependency)
    with pytest.raises(ModuleNotFoundError):
        Geocoder(PACK)
    # An explicitly selected Python backend never attempts to import the extension.
    with Geocoder(PACK, backend="python") as geo:
        assert geo.info()["backend"] == "python"
    with pytest.raises(InvalidInputError):
        Geocoder(PACK, backend="invalid")  # type: ignore[arg-type]


def test_runtime_failure_is_never_retried_with_another_backend() -> None:
    with Geocoder(PACK) as geo:

        def failed(block: int, key: int) -> int:
            raise ValueError("kernel failure")

        geo._stored_cell = failed
        with pytest.raises(ValueError, match="kernel failure"):
            geo.from_h3(finest(BRANCHES[0]))
