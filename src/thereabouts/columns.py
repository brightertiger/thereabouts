"""Bounded analytic columns; integer references are local to one manifest."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from .client_results import Data, Place
from .reading.address import parents
from .reading.batch import Batch
from .reading.pack import Pack


@dataclass(frozen=True, slots=True)
class Columns:
    """Detached read-only arrays, with an optional catalogue for this chunk.

    Zero references are null. ``present`` distinguishes an unassigned stored row
    from absence; ``valid`` distinguishes invalid input from a valid H3 cell.
    References can only be joined within the exact ``data.manifest_sha256``.
    """

    h3: NDArray[np.uint64]
    stored_h3: NDArray[np.uint64]
    valid: NDArray[np.bool_]
    present: NDArray[np.bool_]
    status: NDArray[np.str_]
    country_ref: NDArray[np.uint32]
    state_ref: NDArray[np.uint32]
    city_ref: NDArray[np.uint32]
    flags: NDArray[np.uint32]
    data: Data
    places: Mapping[int, Place] | None
    errors: tuple[str | None, ...]


def columns(pack: Pack, data: Data, batch: Batch, *, decode: bool) -> Columns:
    cell, labels = batch.cells, batch.labels
    valid = cell != 0
    present = batch.keys >= 0
    stored = parents(cell, batch.keys)
    status = np.full(len(cell), "invalid_input", dtype="U16")
    status[valid] = "outside_coverage"
    status[batch.covered] = "ineligible"
    status[present] = "unassigned"
    status[present & np.any(labels[:, :3] != 0, axis=1)] = "matched"
    places = None
    if decode:
        records = {}
        for reference in np.unique(labels[:, :3]):
            value = pack.places.place(int(reference))
            if value is not None:
                records[int(reference)] = value
        places = MappingProxyType(records)
    for array in (cell, stored, valid, present, status, labels):
        array.flags.writeable = False
    return Columns(
        cell,
        stored,
        valid,
        present,
        status,
        labels[:, 0],
        labels[:, 1],
        labels[:, 2],
        labels[:, 3],
        data,
        places,
        batch.errors,
    )
