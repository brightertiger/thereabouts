"""Materialize only the requested row of a numeric batch."""

from typing import cast

from ..packs.spatial import Label
from ..results import Data, InputError, Query, Resolution
from .backend import StoredCell
from .batch import Batch
from .decode import resolution
from .pack import Pack


def result(
    pack: Pack, data: Data, batch: Batch, index: int, stored_cell: StoredCell
) -> Resolution:
    error = batch.errors[index]
    if error is not None:
        return Resolution(
            "invalid_input",
            None,
            (),
            Query(batch.kind),
            None,
            data,
            error=InputError("invalid_input", error),
        )
    cell = int(batch.cells[index])
    query = (
        Query(
            "coordinates",
            float(batch.coordinates[index, 0]),
            float(batch.coordinates[index, 1]),
        )
        if batch.kind == "coordinates"
        else Query("h3", h3=f"{cell:x}")
    )
    found = None
    if batch.keys[index] >= 0:
        found = (
            int(batch.keys[index]),
            cast(Label, tuple(map(int, batch.labels[index]))),
        )
    return resolution(
        pack,
        data,
        query,
        cell,
        int(batch.blocks[index]),
        bool(batch.covered[index]),
        found,
        stored_cell,
    )
