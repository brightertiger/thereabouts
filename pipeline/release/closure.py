"""Refuse the place references the client pack writer refuses, before publishing.

The writer (`core/thereabouts-writer/src/{catalogue,forward_catalogue,names,phone}.rs`)
seeds its catalogue from cell and forward-table references, every canonical city and
every country, state, city or self-normalized place. It then follows each place's
country, parent, sovereign and normalized city. Every reached ID must be one unique
place; a reached place's mapping must equal its normalized city; names must name a
canonical city. Places nothing reaches may refer anywhere, as in the writer.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypeAlias

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .source import Row

Strings: TypeAlias = "pa.Array[Any]"
Values: TypeAlias = "pa.Array[Any] | pa.ChunkedArray[Any]"

# Tables whose rows the writer seeds from: cells for core, each forward family's
# primary table, and phone metadata with phone prefixes.
SEEDED = (
    "cells",
    "postal_codes",
    "airports",
    "trade_locations",
    "ip_ranges",
    "phone_prefixes",
    "phone_metadata",
)
REFERENCES = ("country_id", "state_id", "city_id", "place_id")
EDGES = ("parent_id", "sovereign_id", "normalized_city_id")
SEED_ROLES = ["country", "state", "city"]
# A published non-geographic calling code with no country place.
NON_GEOGRAPHIC = "001"
# Dangling references named in an error.
SHOWN = 20


def files(directory: Path, tables: list[Row], kind: str) -> list[Path]:
    return [directory / t["path"] for t in tables if t["kind"] == kind]


def read(directory: Path, tables: list[Row], kind: str, names: list[str]) -> pa.Table:
    """The named columns that this table declares, from every file."""
    parts = []
    for path in files(directory, tables, kind):
        present = [name for name in names if name in pq.read_schema(path).names]
        parts.append(pq.read_table(path, columns=present))
    if not parts:
        return pa.table({name: pa.array([], pa.string()) for name in names})
    return pa.concat_tables(parts).combine_chunks()


def unique(values: Values) -> Strings:
    """Distinct non-null strings."""
    table = pa.table({"id": values}).filter(~pc.field("id").is_null())
    return table.group_by("id").aggregate([])["id"].combine_chunks()


def absent(values: Strings, known: Strings) -> Strings:
    """Values not in `known`."""
    table = pa.table({"id": values}).filter(~pc.field("id").isin(known))
    return table["id"].combine_chunks()


def first(values: Values) -> str:
    """A deterministic example for an error message."""
    return sorted(str(value) for value in values.to_pylist())[0]


def every(values: Values) -> str:
    """The values, sorted, for an error message; long lists are cut short."""
    names = sorted(str(value) for value in values.to_pylist())
    more = f" and {len(names) - SHOWN} more" if len(names) > SHOWN else ""
    return ", ".join(names[:SHOWN]) + more


def countries(codes: Iterator[str | None]) -> Strings:
    """The writer's country place for each code; the non-geographic code has none."""
    found = {f"country:{code}" for code in codes if code and code != NON_GEOGRAPHIC}
    return pa.array(sorted(found), pa.string())


def seeds(directory: Path, tables: list[Row]) -> Iterator[Strings]:
    for kind in SEEDED:
        for path in files(directory, tables, kind):
            names = pq.read_schema(path).names
            for name in REFERENCES:
                if name in names:
                    yield unique(pq.read_table(path, columns=[name])[name])
            if not kind.startswith("phone_"):
                continue
            if "place_ids" in names:
                listed = pq.read_table(path, columns=["place_ids"])["place_ids"]
                yield unique(pc.list_flatten(listed))
            for name in ("country_codes", "territory"):
                if name in names:
                    value = pq.read_table(path, columns=[name])[name]
                    codes = pc.list_flatten(value) if name == "country_codes" else value
                    yield countries(iter(unique(codes).to_pylist()))
    yield unique(read(directory, tables, "canonical_cities", ["city_id"])["city_id"])


def check(directory: Path, tables: list[Row]) -> dict[str, int]:
    """Raise on the references the writer would refuse; count the closure.

    Dangling references are named together, from the first frontier that has any."""
    places = read(
        directory, tables, "places", ["place_id", "role", "country_code", *EDGES]
    )
    if places["place_id"].null_count:
        raise ValueError("Place lacks a place ID")
    repeated = (
        places.group_by("place_id")
        .aggregate([("place_id", "count")])
        .filter(pc.field("place_id_count") > 1)
    )
    if repeated.num_rows:
        raise ValueError(f"Duplicate place ID: {first(repeated['place_id'])}")
    lacking = places.filter(pc.field("country_code").is_null())
    if lacking.num_rows:
        raise ValueError(f"Place lacks a country code: {first(lacking['place_id'])}")
    identifiers = places["place_id"].combine_chunks()
    roots = places.filter(
        pc.field("role").isin(SEED_ROLES)
        | (pc.field("normalized_city_id") == pc.field("place_id"))
    )["place_id"]
    frontier = unique(pa.chunked_array([*seeds(directory, tables), unique(roots)]))
    reached = frontier
    while len(frontier):
        dangling = absent(frontier, identifiers)
        if len(dangling):
            raise ValueError(f"Dangling dataset place reference: {every(dangling)}")
        rows = places.filter(pc.field("place_id").isin(frontier))
        following = unique(
            pa.chunked_array(
                [
                    # The writer replaces each place's country_id by its own code.
                    countries(iter(unique(rows["country_code"]).to_pylist())),
                    *(unique(rows[name]) for name in EDGES),
                ]
            )
        )
        frontier = absent(following, reached)
        reached = pa.concat_arrays([reached, frontier])
    mappings(directory, tables, places, reached)
    names(directory, tables)
    return {"places": len(identifiers), "reached": len(reached)}


def mappings(
    directory: Path, tables: list[Row], places: pa.Table, reached: Strings
) -> None:
    mapped = read(directory, tables, "place_to_city", ["place_id", "city_id"])
    joined = mapped.filter(pc.field("place_id").isin(reached)).join(
        places.select(["place_id", "normalized_city_id"]), "place_id"
    )
    city, normalized = pc.field("city_id"), pc.field("normalized_city_id")
    wrong = joined.filter(
        (city.is_null() != normalized.is_null())
        | (~city.is_null() & ~normalized.is_null() & (city != normalized))
    )
    if wrong.num_rows:
        example = first(wrong["place_id"])
        raise ValueError(f"Place mapping disagrees with catalogue: {example}")


def names(directory: Path, tables: list[Row]) -> None:
    canonical = read(directory, tables, "canonical_cities", ["city_id"])["city_id"]
    cities = read(directory, tables, "names", ["city_id"])["city_id"]
    dangling = absent(unique(cities), unique(canonical))
    if len(dangling):
        raise ValueError(f"Name references a noncanonical city: {first(dangling)}")
