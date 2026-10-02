"""Validate rows and group block reads, preserving the original row positions."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from ..client_errors import InvalidInputError
from ..packs.address import address
from ..packs.spatial import Label
from ..results import Query
from .inputs import Errors, coordinates, h3_cell
from .pack import Pack


@dataclass(frozen=True)
class Hit:
    query: Query
    cell: int = 0
    block: int = 0
    covered: bool = False
    found: tuple[int, Label] | None = None
    error: str | None = None


def lookup_rows(
    pack: Pack,
    rows: list[object],
    kind: Literal["coordinates", "h3"],
    errors: Errors,
) -> list[Hit]:
    normalize = coordinates if kind == "coordinates" else h3_cell
    groups: dict[int, list[tuple[int, int, Query, int]]] = defaultdict(list)
    hits: dict[int, Hit] = {}
    for index, row in enumerate(rows):
        try:
            cell, query = normalize(row)
        except InvalidInputError as exc:
            if errors == "raise":
                raise
            hits[index] = Hit(Query(kind), error=str(exc))
            continue
        block, key = address(cell, 8)
        groups[block].append((index, cell, query, key))
    for block in sorted(groups):
        group = groups[block]
        found = pack.lookup_many(block, [row[3] for row in group])
        for position, (index, cell, query, _) in enumerate(group):
            hits[index] = Hit(
                query,
                cell,
                block,
                found is not None,
                None if found is None else found[position],
            )
    return [hits[index] for index in range(len(rows))]
