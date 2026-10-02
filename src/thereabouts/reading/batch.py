"""Normalize bounded chunks and search shards without constructing result objects."""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from h3.api import basic_int as h3
from numpy.typing import NDArray

from ..client_errors import InvalidInputError
from .address import addresses
from .inputs import Errors, coordinate_values, h3_value
from .pack import Pack

Kind = Literal["coordinates", "h3"]


@dataclass(frozen=True, slots=True)
class Batch:
    cells: NDArray[np.uint64]
    coordinates: NDArray[np.float64]
    kind: Kind
    errors: tuple[str | None, ...]
    blocks: NDArray[np.int64]
    covered: NDArray[np.bool_]
    keys: NDArray[np.int64]
    labels: NDArray[np.uint32]


def lookup_rows(pack: Pack, rows: list[object], kind: Kind, errors: Errors) -> Batch:
    cells, points = [], []
    failures: list[str | None] = []
    for row in rows:
        try:
            if kind == "coordinates":
                lat, lon = coordinate_values(row)
                cell = h3.latlng_to_cell(lat, lon, 8)
            else:
                lat, lon = 0.0, 0.0
                cell = h3_value(row)
            cells.append(cell)
            points.append((lat, lon))
            failures.append(None)
        except InvalidInputError as exc:
            if errors == "raise":
                raise
            cells.append(0)
            points.append((0.0, 0.0))
            failures.append(str(exc))
    pack.ensure_open()
    numeric = np.array(cells, dtype=np.uint64)
    blocks, keys = addresses(numeric)
    stored = np.full(len(rows), -1, dtype=np.int64)
    covered = np.zeros(len(rows), dtype=np.bool_)
    labels = np.zeros((len(rows), 4), dtype=np.uint32)
    shards = np.searchsorted(pack.block_starts, blocks, side="right") - 1
    for shard in np.unique(shards[numeric != 0]):
        if shard < 0:
            continue
        indices = np.flatnonzero((shards == shard) & (numeric != 0))
        record = pack.cells[shard]
        index = pack.index_for(record["first_block"])
        assert index is not None
        indices = indices[np.isin(blocks[indices], index.ids)]
        if not len(indices):
            continue
        covered[indices] = True
        stored[indices], labels[indices] = index.lookup_many(
            blocks[indices], keys[indices]
        )
    if np.any((numeric != 0) & ~covered):
        pack._absent_block()
    return Batch(
        numeric,
        np.array(points, dtype=np.float64),
        kind,
        tuple(failures),
        blocks,
        covered,
        stored,
        labels,
    )
