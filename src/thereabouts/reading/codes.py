"""Decode stored code candidates; no geographic reassignment or implicit selection."""

from dataclasses import dataclass
from typing import Any

from h3.api import basic_int as h3

from ..packs.code_records import payload
from ..packs.errors import CorruptPackError
from ..packs.keys import country_code, key, normalize
from ..packs.layout import (
    CITY_METHOD_MASK,
    CITY_METHODS,
    COUNTRY_AREA,
    OFFSHORE,
    STATE_AREA,
)
from ..results import (
    Candidate,
    Confidence,
    Data,
    Distance,
    Methods,
    Observation,
    Query,
    Reference,
    Resolution,
    SourcePlace,
    Status,
    Warning,
    freeze_object,
)
from .pack import Pack


def observation(pack: Pack, row: dict[str, Any]) -> Observation:
    reference = row["reference"]
    point = None
    if reference is not None:
        stored = reference["stored_h3"]
        point = Reference(
            reference["h3"],
            8,
            stored,
            None if stored is None else h3.get_resolution(int(stored, 16)),
        )
    flags = row["flags"]
    country, state, city = (pack.identity(ref) for ref in row["refs"])
    methods = Methods(
        CITY_METHODS[flags & CITY_METHOD_MASK],
        "area" if flags & STATE_AREA else None,
        "area" if flags & COUNTRY_AREA else None,
        "unknown"
        if reference is None or reference["stored_h3"] is None
        else "offshore"
        if flags & OFFSHORE
        else "land",
    )
    return Observation(
        source=row["source"],
        source_id=row["source_id"],
        source_release=row["source_release"],
        license=row["license"],
        golden_table=row["golden_table"],
        fields=freeze_object(row["fields"]),
        reference=point,
        country_id=country,
        state_id=state,
        city_id=city,
        methods=methods,
        cell_status=row["cell_status"],
        country_disagrees=row["country_disagrees"],
    )


def candidate(pack: Pack, row: dict[str, Any]) -> Candidate:
    country_ref, state_ref, city_ref = row["refs"]
    country_entry = pack.places.get(country_ref)
    country = None if country_entry is None else country_entry.place
    sovereign = (
        None if country_entry is None else pack.places.place(country_entry.sovereign)
    )
    entity = row["entity"]
    place = (
        None
        if entity is None
        else SourcePlace(
            entity["id"],
            entity["name"],
            entity["role"],
            entity["country_code"],
            freeze_object(entity["codes"]),
            entity["type"],
        )
    )
    return Candidate(
        id=row["id"],
        place=place,
        city=pack.places.place(city_ref),
        state=pack.places.place(state_ref),
        country=country,
        sovereign=sovereign,
        relationship="source_association",
        methods=Methods(**row["methods"]),
        confidence=Confidence("exact_code_link"),
        distance=None if row["distance"] is None else Distance(**row["distance"]),
        observations=tuple(observation(pack, item) for item in row["observations"]),
    )


@dataclass(frozen=True, slots=True)
class Matches:
    candidates: tuple[Candidate, ...]
    warnings: tuple[Warning, ...]


def matches(pack: Pack, wanted: str) -> Matches:
    cached = pack.cache.get(wanted)
    if cached is not None:
        assert isinstance(cached, Matches)
        return cached
    rows: list[dict[str, Any]] = []
    shard = pack.exact_for(wanted)
    if shard is not None:
        try:
            position = shard.position(wanted)
            if position is not None:
                result = shard.payload(position)
                payload(result, pack.manifest["place_count"])
                rows = result["candidates"]
        except (ValueError, KeyError, TypeError) as exc:
            raise CorruptPackError(f"Invalid exact-key payload: {exc}") from exc
    decoded = Matches(
        tuple(candidate(pack, row) for row in rows),
        tuple(
            Warning(code)
            for code in sorted({code for row in rows for code in row["warnings"]})
        ),
    )
    pack.cache.put(wanted, decoded)
    return decoded


def lookup(
    pack: Pack, data: Data, value: str, country: str | None, scheme: str | None
) -> Resolution:
    family = pack.manifest["family"]
    country = None if country is None else country_code(country)
    code = normalize(value, pack.manifest["key_normalization"], country)
    wanted = key(family, code, country, scheme)
    query = Query(
        "postal" if family == "postal" else "airport",
        value=code,
        country=country,
        scheme=scheme,
    )
    found = matches(pack, wanted)
    candidates, warnings = found.candidates, found.warnings
    selected = candidates[0] if len(candidates) == 1 else None
    status: Status = (
        "matched" if selected else "ambiguous" if candidates else "not_found"
    )
    return Resolution(
        status=status,
        selected=selected,
        candidates=candidates,
        query=query,
        reference=None,
        data=data,
        warnings=warnings,
    )
