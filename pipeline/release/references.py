"""Resolve references to place keys that no row defines, as release config directs.

Every declared relationship to `places`, `canonical_cities` or `countries`, every
`place_ids` list and every code the pack writer looks up as `country:<code>`
(`closure.py`) must name an existing key. `release.dataset.closure` decides each
missing key: an alias rewrites it to the key that covers it, an exclusion drops
the rows that refer to it, and anything else refuses the release, naming every
missing key at once. An existing key is never rewritten. Each change is counted
per table, column and key for the manifest's `closure` record.
"""

import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from pipeline.config.release import ClosureRules, DatasetLimits
from pipeline.files import file_record

from .budget import Budget, Sink
from .closure import NON_GEOGRAPHIC, Strings, Values, absent, files, read, unique
from .source import Row
from .tables import parquet

# The key column of each referenced table; countries are keyed by a bare code.
KEYS = {
    "places": "place_id",
    "canonical_cities": "city_id",
    "countries": "country_code",
}
# Columns the pack writer reads as country codes and looks up as country places.
WRITER_CODES = (
    ("places", "country_code"),
    ("phone_metadata", "territory"),
    ("phone_prefixes", "country_codes"),
)
LISTED = "place_ids"
COUNTRY = "country:"
# Besides the referenced tables, whose lost rows would orphan references in turn,
# these keep every row: cells index each block's row group, and every place has
# exactly one mapping.
KEPT = {"cells", "place_to_city"}
# Missing keys named per column when a release is refused.
SHOWN = 10


@dataclass(frozen=True, order=True)
class Reference:
    table: str
    column: str
    target: str
    code: bool  # holds `<code>` for the key `country:<code>`
    listed: bool  # holds a list of values


@dataclass(frozen=True)
class Change:
    table: str
    column: str
    place: str
    to: str | None  # the alias; None drops the referring rows
    rows: int


def specifications(descriptions: Row) -> dict[tuple[str, str], Reference]:
    """Every column that names a place, canonical city or country key."""
    found = {}
    for table, description in descriptions.items():
        types = {c["name"]: c["type"] for c in description["columns"]}
        named = [
            (relationship["columns"][0], relationship["references"]["table"])
            for relationship in description["relationships"]
            if relationship["references"]["table"] in KEYS
        ]
        named += [(c, "places") for t, c in WRITER_CODES if t == table and c in types]
        if LISTED in types:
            named.append((LISTED, "places"))
        for column, target in named:
            code = target == "countries" or (table, column) in WRITER_CODES
            listed = types[column].startswith("list")
            found[(table, column)] = Reference(table, column, target, code, listed)
    return dict(sorted(found.items()))


def prefixed(codes: Strings) -> Strings:
    return pc.replace_substring_regex(codes, pattern="^", replacement=COUNTRY)


def identifiers(values: Values, reference: Reference) -> Strings:
    """The key each value names, as a place ID; lists are flattened."""
    flat = pc.list_flatten(values) if reference.listed else values
    if isinstance(flat, pa.ChunkedArray):
        flat = flat.combine_chunks()
    return prefixed(flat) if reference.code else flat


def stored(place: str, reference: Reference) -> str:
    """A place ID as the column stores it."""
    return place.removeprefix(COUNTRY) if reference.code else place


def defined(directory: Path, tables: list[Row], target: str) -> Strings:
    keys = unique(read(directory, tables, target, [KEYS[target]])[KEYS[target]])
    return prefixed(keys) if target == "countries" else keys


def referenced(
    directory: Path, tables: list[Row], references: list[Reference]
) -> dict[Reference, Strings]:
    """The distinct keys that each of one table's references names."""
    parts: dict[Reference, list[Strings]] = defaultdict(list)
    for path in files(directory, tables, references[0].table):
        present = set(pq.read_schema(path).names)
        found = [r for r in references if r.column in present]
        data = pq.read_table(path, columns=[r.column for r in found])
        for reference in found:
            values = identifiers(data[reference.column], reference)
            parts[reference].append(unique(values))
    # The writer publishes the non-geographic calling code without a country.
    excused = pa.array([COUNTRY + NON_GEOGRAPHIC])
    named = {}
    for reference in references:
        values = unique(pa.chunked_array(parts.pop(reference, []), pa.string()))
        named[reference] = absent(values, excused) if reference.code else values
    return named


def lacking(values: Strings, known: Strings) -> Strings:
    """`values` not in `known`, hashing the values rather than millions of keys."""
    return absent(values, known.filter(pc.is_in(known, value_set=values)))


def missing(
    directory: Path, tables: list[Row], references: list[Reference]
) -> tuple[dict[Reference, list[str]], dict[str, Strings]]:
    """Missing keys per reference, with each target's defined keys.

    One table's distinct references are held at a time, so the peak is about the
    places' own keys and edges."""
    keys = {r.target: defined(directory, tables, r.target) for r in references}
    found = {}
    for table in sorted({r.table for r in references}):
        same = [r for r in references if r.table == table]
        for reference, values in referenced(directory, tables, same).items():
            lost = lacking(values, keys[reference.target])
            if len(lost):
                found[reference] = sorted(str(value) for value in lost.to_pylist())
    return found, keys


def naming(values: Values, reference: Reference, places: list[str]) -> pa.Table:
    """The row index and place of every value that names one of `places`."""
    rows = (
        pc.list_parent_indices(values)
        if reference.listed
        else pa.array(range(len(values)), pa.int64())
    )
    hits = pa.table({"row": rows, "id": identifiers(values, reference)})
    return hits.filter(pc.is_in(pc.field("id"), pa.array(places, pa.string())))


def counted(
    directory: Path, tables: list[Row], reference: Reference, places: list[str]
) -> dict[str, int]:
    """Rows that name each place."""
    totals: dict[str, int] = defaultdict(int)
    for path in files(directory, tables, reference.table):
        values = pq.read_table(path, columns=[reference.column])[reference.column]
        hits = naming(values.combine_chunks(), reference, places)
        grouped = hits.group_by("id").aggregate([("row", "count_distinct")])
        for place, rows in zip(
            grouped["id"].to_pylist(),
            grouped["row_count_distinct"].to_pylist(),
            strict=True,
        ):
            totals[str(place)] += cast(int, rows)
    return totals


def listing(found: dict[Reference, list[str]]) -> str:
    parts = []
    for reference, places in sorted(found.items()):
        shown = ", ".join(places[:SHOWN])
        more = f" and {len(places) - SHOWN} more" if len(places) > SHOWN else ""
        parts.append(f"{reference.table}.{reference.column}: {shown}{more}")
    return "; ".join(parts)


def plan(
    directory: Path, tables: list[Row], descriptions: Row, rules: ClosureRules
) -> list[Change]:
    """Decide every missing key without writing; refuse the undecided ones."""
    references = list(specifications(descriptions).values())
    found, keys = missing(directory, tables, references)
    protected = {*KEYS, *KEPT}
    decided: dict[Reference, dict[str, str | None]] = defaultdict(dict)
    unlisted: dict[Reference, list[str]] = defaultdict(list)
    kept: dict[Reference, list[str]] = defaultdict(list)
    for reference, places in found.items():
        for place in places:
            kind, _, code = place.partition(":")
            alias = rules.place_aliases.get(kind, {}).get(code)
            excluded = rules.unknown_places == "exclude" or code in (
                rules.excluded_places.get(kind, [])
            )
            if alias is not None:
                decided[reference][place] = f"{kind}:{alias}"
            elif not excluded:
                unlisted[reference].append(place)
            elif reference.table in protected:
                kept[reference].append(place)
            else:
                decided[reference][place] = None
    if unlisted:
        raise ValueError(
            "Dangling dataset place references; alias or exclude them in "
            f"release.dataset.closure: {listing(unlisted)}"
        )
    if kept:
        raise ValueError(
            "Dangling dataset place references whose rows cannot be excluded: "
            f"{listing(kept)}"
        )
    unresolved: dict[Reference, list[str]] = defaultdict(list)
    for reference, choices in decided.items():
        targets = pa.array([to for to in choices.values() if to], pa.string())
        lacking = set(absent(targets, keys[reference.target]).to_pylist())
        unresolved[reference] += [
            f"{p} -> {to}" for p, to in choices.items() if to in lacking
        ]
    if any(unresolved.values()):
        raise ValueError(
            "Closure alias target is not defined: "
            f"{listing({r: p for r, p in unresolved.items() if p})}"
        )
    changes = []
    for reference, choices in sorted(decided.items()):
        rows = counted(directory, tables, reference, sorted(choices))
        changes += [
            Change(reference.table, reference.column, place, to, rows[place])
            for place, to in sorted(choices.items())
        ]
    return changes


def renamed(values: Values, reference: Reference, aliases: dict[str, str]) -> Values:
    codes = {stored(p, reference): stored(to, reference) for p, to in aliases.items()}
    if not reference.listed:
        for source, target in codes.items():
            matched = pc.equal(values, pa.scalar(source, pa.string()))
            values = cast(Values, pc.if_else(matched, target, values))
        return values
    lists = []
    for value in values.to_pylist():
        if value is None or not codes.keys() & set(value):
            lists.append(value)
            continue
        # A list that already names the alias keeps one copy of it.
        lists.append(list(dict.fromkeys(codes.get(item, item) for item in value)))
    return cast(Values, pa.array(lists, values.type))


def resolved(
    group: pa.Table, changes: list[Change], references: dict[tuple[str, str], Reference]
) -> pa.Table:
    by_column: dict[str, list[Change]] = defaultdict(list)
    for change in changes:
        by_column[change.column].append(change)
    dropped: set[int] = set()
    for name, selected in by_column.items():
        reference = references[(selected[0].table, name)]
        values = group[name].combine_chunks()
        excluded = [c.place for c in selected if c.to is None]
        dropped.update(
            cast(list[int], naming(values, reference, excluded)["row"].to_pylist())
        )
        aliases = {c.place: c.to for c in selected if c.to is not None}
        if aliases and naming(values, reference, list(aliases)).num_rows:
            index = group.schema.get_field_index(name)
            field = group.schema.field(name)
            group = group.set_column(index, field, renamed(values, reference, aliases))
    if not dropped:
        return group
    return group.filter(pa.array([row not in dropped for row in range(group.num_rows)]))


def rewrite(
    directory: Path,
    record: Row,
    changes: list[Change],
    references: dict[tuple[str, str], Reference],
    limits: DatasetLimits,
    budget: Budget,
) -> Row:
    """Rewrite one file row group by row group, so cells keep their block index."""
    path = directory / record["path"]
    temporary = path.with_name(f".closure-{path.name}")
    rows = 0
    with (
        pq.ParquetFile(path) as source,
        Sink(temporary, budget) as sink,
        parquet(sink, source.schema_arrow, limits) as writer,
    ):
        for index in range(source.num_row_groups):
            group = resolved(source.read_row_group(index), changes, references)
            if group.num_rows:
                writer.write_table(group, row_group_size=group.num_rows)
                rows += group.num_rows
    os.replace(temporary, path)
    return {**record, **file_record(directory, path), "rows": rows}


def apply(
    directory: Path,
    tables: list[Row],
    changes: list[Change],
    descriptions: Row,
    limits: DatasetLimits,
    budget: Budget,
) -> list[Row]:
    """Rewrite each file whose table has a change; others are returned as they are."""
    references = specifications(descriptions)
    by_table: dict[str, list[Change]] = defaultdict(list)
    for change in changes:
        by_table[change.table].append(change)
    return [
        rewrite(directory, record, by_table[record["kind"]], references, limits, budget)
        if record["kind"] in by_table
        else record
        for record in tables
    ]


def record(rules: ClosureRules, changes: list[Change], reached: dict[str, int]) -> Row:
    """The manifest's account of every rewritten and dropped reference."""

    def entry(change: Change) -> Row:
        alias = {"to": change.to} if change.to else {}
        return {
            "table": change.table,
            "column": change.column,
            "place": change.place,
            **alias,
            "rows": change.rows,
        }

    return {
        "unknown_places": rules.unknown_places,
        "aliased": [entry(c) for c in changes if c.to],
        "excluded": [entry(c) for c in changes if not c.to],
        **reached,
    }
