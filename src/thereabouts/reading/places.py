"""Lazy place decoding and public identity projection."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..client_results import Evidence, Place, freeze
from .cache import Cache

if TYPE_CHECKING:
    from .pack import Pack


@dataclass(frozen=True, slots=True)
class Entry:
    place: Place
    sovereign: int


class Places:
    def __init__(self, pack: "Pack", cache: Cache) -> None:
        self.pack, self.cache = pack, cache

    def get(self, reference: int) -> Entry | None:
        if not reference:
            return None
        cached = self.cache.get(reference)
        if cached is not None:
            assert isinstance(cached, Entry)
            return cached
        entry = self._decode(reference)
        self.cache.put(reference, entry)
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
