"""Select once on open; runtime failures never cause a silent backend change."""

import importlib
from collections.abc import Callable
from typing import Literal

from ..client_errors import InvalidInputError
from ._reader_py import stored_cell

Backend = Literal["auto", "python"]
StoredCell = Callable[[int, int], int]
MODULE = "thereabouts.reading._reader_cy"


def select(backend: Backend) -> tuple[str, StoredCell]:
    if backend == "python":
        return "python", stored_cell
    if backend != "auto":
        raise InvalidInputError("backend must be 'auto' or 'python'")
    try:
        native = importlib.import_module(MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != MODULE:
            raise
        return "python", stored_cell
    return "cython", native.stored_cell
