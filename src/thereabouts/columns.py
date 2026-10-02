"""Bounded analytic columns; integer references are local to one manifest."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from numpy.typing import NDArray

from .packs.address import cell_at
from .reading.batch import Hit
from .reading.decode import place
from .reading.pack import Pack
from .results import Data, Place


@dataclass(frozen=True)
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


def columns(pack: Pack, data: Data, hits: list[Hit], *, decode: bool) -> Columns:
    count = len(hits)
    cell = np.zeros(count, dtype=np.uint64)
    stored = np.zeros(count, dtype=np.uint64)
    valid = np.zeros(count, dtype=np.bool_)
    present = np.zeros(count, dtype=np.bool_)
    status = np.empty(count, dtype="U16")
    labels = np.zeros((count, 4), dtype=np.uint32)
    for index, hit in enumerate(hits):
        valid[index] = hit.error is None
        cell[index] = hit.cell
        if hit.error is not None:
            status[index] = "invalid_input"
        elif not hit.covered:
            status[index] = "outside_coverage"
        elif hit.found is None:
            status[index] = "ineligible"
        else:
            key, label = hit.found
            present[index] = True
            stored[index] = cell_at(hit.block, key)
            labels[index] = label
            status[index] = "matched" if any(label[:3]) else "unassigned"
    places = None
    if decode:
        records = {}
        for reference in np.unique(labels[:, :3]):
            value = place(pack, int(reference))
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
        tuple(hit.error for hit in hits),
    )
