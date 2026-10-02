"""Lazy decoded places, charged by retained bytes rather than entry count."""

import sys
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from typing import TYPE_CHECKING

from ..results import Evidence, Place, freeze

if TYPE_CHECKING:
    from .pack import Pack

# The populated benchmark retains 4,176 evidence-bearing places in this budget.
DEFAULT_CACHE_BYTES = 32 * 1024 * 1024


def retained_bytes(value: object, seen: set[int] | None = None) -> int:
    """Conservatively charge shared objects once per entry (not across entries)."""
    if seen is None:
        seen = set()
    if id(value) in seen:
        return 0
    seen.add(id(value))
    size = sys.getsizeof(value)
    if is_dataclass(value) and not isinstance(value, type):
        size += sum(retained_bytes(getattr(value, f.name), seen) for f in fields(value))
    elif isinstance(value, Mapping):
        # MappingProxyType doesn't include its backing dictionary in getsizeof.
        size += sys.getsizeof(dict(value))
        size += sum(
            retained_bytes(key, seen) + retained_bytes(item, seen)
            for key, item in value.items()
        )
    elif isinstance(value, tuple):
        size += sum(retained_bytes(item, seen) for item in value)
    return size


@dataclass(frozen=True, slots=True)
class Entry:
    place: Place
    sovereign: int


class Places:
    def __init__(self, pack: "Pack", budget: int) -> None:
        self.pack = pack
        self.budget = budget
        self.entries: OrderedDict[int, tuple[Entry, int]] = OrderedDict()
        self.bytes = 0
        self.hits = self.misses = self.evictions = 0

    def get(self, reference: int) -> Entry | None:
        if not reference:
            return None
        cached = self.entries.get(reference)
        if cached is not None:
            self.entries.move_to_end(reference)
            self.hits += 1
            return cached[0]
        self.misses += 1
        entry = self._decode(reference)
        if self.budget:
            size = retained_bytes((reference, entry, 0))
            # Dictionary allocation is included separately, including spare slots.
            self.entries[reference] = (entry, size)
            self.bytes += size
            while (
                self.entries and self.bytes + sys.getsizeof(self.entries) > self.budget
            ):
                _, (_, removed) = self.entries.popitem(last=False)
                self.bytes -= removed
                self.evictions += 1
            if not self.entries:
                self.entries.clear()
        return entry

    def place(self, reference: int) -> Place | None:
        entry = self.get(reference)
        return None if entry is None else entry.place

    def _decode(self, reference: int) -> Entry:
        row = self.pack.record(reference)
        evidence = row["evidence"]
        place = Place(
            id=row["place_id"],
            name=row["name"],
            name_en=row["name_en"],
            local_name=row["local_name"],
            role=row["role"],
            settlement_kind=row["settlement_kind"],
            country_code=row["country_code"],
            code=row["code"],
            code_status=row["code_status"],
            code_system=None,
            country_id=self.pack.identity(row["country_id"]),
            parent_id=self.pack.identity(row["parent_id"]),
            sovereign_id=self.pack.identity(row["sovereign_id"]),
            normalized_city_id=self.pack.identity(row["normalized_city_id"]),
            parent_method=row["parent_method"],
            normalization_method=row["normalization_method"],
            evidence=Evidence(
                evidence["golden_table"],
                freeze(evidence["source_ids"]),
                freeze(evidence["name_provenance"]),
            ),
        )
        return Entry(place, row["sovereign_id"])

    def info(self) -> dict[str, int]:
        return {
            "budget_bytes": self.budget,
            "entries": len(self.entries),
            "retained_bytes": self.bytes
            + (sys.getsizeof(self.entries) if self.entries else 0),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
        }

    def clear(self) -> None:
        self.entries.clear()
        self.bytes = 0
