"""Join canonical cities to their source names, filter by policy, publish one table."""

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pyarrow as pa

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import Resources
from pipeline.engines import query
from pipeline.engines.artifact_io import parquet
from pipeline.runtime.jsonio import write_json

from .policy import Policy, folded, guard_key, parse

Row = dict[str, Any]
# GeoNames places carry their ASCII spelling only in provenance.
ASCII_FIELD = "asciiname"
# Lists of other names in a place's provenance are the aliases the names
# partition already carries; repeating them on every row adds nothing.
OMITTED_PROVENANCE = ("alternate_names_untyped",)
KINDS = {"english": 0, "alternate": 1, "ascii": 2}
TREATMENTS = {"keep": 0, "guarded": 1, "drop": 2}
SCHEMA = pa.schema(
    [
        pa.field("city_id", pa.string(), False),
        pa.field("name", pa.string(), False),
        pa.field("kind", pa.string(), False),
        pa.field("language", pa.string()),
        pa.field("country_code", pa.string(), False),
        pa.field("place_id", pa.string(), False),
        pa.field("source", pa.string(), False),
        pa.field("source_id", pa.string(), False),
        pa.field("source_release", pa.string(), False),
        pa.field("license", pa.string(), False),
        pa.field("provenance", pa.string(), False),
    ]
)
COLUMNS = (
    "l.city_id, l.place_id, l.country_code, n.source, n.source_id, n.name, "
    "n.source_release, n.license, n.provenance"
)
ALIASES = f"""SELECT {COLUMNS}, n.language, n.is_preferred, n.is_short,
  n.is_colloquial, n.is_historic OR n.valid_to IS NOT NULL AS is_historic, 0 AS origin
  FROM {{view}} n JOIN links l ON l.source = n.source AND l.id = n.entity_source_id"""
PLACES = f"""SELECT {COLUMNS}, NULL AS language, false AS is_preferred,
  false AS is_short, false AS is_colloquial, false AS is_historic, 1 AS origin
  FROM {{view}} n JOIN links l ON l.source = n.source AND l.id = n.source_id"""


def literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def view(db: Any, name: str, records: list[Row]) -> None:
    db.read_parquet([r["path"] for r in records]).create_view(name)


def candidates(db: Any, sources: dict[str, list[Row]], policy: Policy) -> Iterator[Row]:
    """Every name row of a linked source record, ordered by city."""
    methods = ",".join(map(literal, policy.linked_methods))
    db.execute(
        f"""CREATE TEMP TABLE links AS
        SELECT DISTINCT m.city_id, m.place_id, c.country_code, u.source, u.id
        FROM place_to_city m
        JOIN canonical_cities c ON c.city_id = m.city_id
        JOIN places p ON p.place_id = m.place_id
        CROSS JOIN LATERAL (SELECT unnest(from_json(p.source_ids,
          '[{{"source":"VARCHAR","id":"VARCHAR"}}]'), recursive := true)) u
        WHERE m.method IN ({methods})"""
    )
    parts = []
    for number, records in enumerate(sources[s] for s in sorted(sources)):
        for kind, template in (("names", ALIASES), ("places", PLACES)):
            selected = [r for r in records if r["kind"] == kind]
            if selected:
                name = f"{kind}_{number}"
                view(db, name, selected)
                parts.append(template.format(view=name))
    if not parts:
        return
    sql = " UNION ALL ".join(parts) + " ORDER BY city_id"
    for batch in db.execute(sql).to_arrow_reader(1024):
        for row in batch.to_pylist():
            yield from expand(row)


def expand(row: Row) -> Iterator[Row]:
    if not row["origin"]:
        language = row["language"] or ""
        english = language == "en" or language.startswith("en-")
        yield row | {"kind": "english" if english else "alternate"}
        return
    provenance = json.loads(row["provenance"])
    ascii_name = provenance.get(ASCII_FIELD)
    for key in OMITTED_PROVENANCE:
        provenance.pop(key, None)
    for kind, name in (("alternate", row["name"]), ("ascii", ascii_name)):
        if name:
            value = provenance | {
                "name_field": ASCII_FIELD if kind == "ascii" else "name"
            }
            yield row | {
                "kind": kind,
                "name": name,
                "provenance": json.dumps(value, ensure_ascii=False, sort_keys=True),
            }


def treatment(row: Row, policy: Policy) -> tuple[str, str]:
    """The strictest treatment among the row's flags, and the flag that set it."""
    flags = [
        (getattr(policy, flag), flag)
        for flag in ("colloquial", "historic", "short")
        if row[f"is_{flag}"]
    ]
    return max(flags, key=lambda item: TREATMENTS[item[0]], default=("keep", ""))


def select(
    rows: list[Row],
    own: set[str],
    guard: dict[str, set[str]],
    policy: Policy,
    dropped: Counter[str],
) -> list[Row]:
    def rank(row: Row) -> tuple[Any, ...]:
        return (
            TREATMENTS[treatment(row, policy)[0]],
            not row["is_preferred"],
            KINDS[row["kind"]],
            row["origin"],
            row["source"],
            row["source_id"],
            row["name"],
        )

    kept: dict[str, Row] = {}
    for row in sorted(rows, key=rank):
        rule, flag = treatment(row, policy)
        key = folded(row["name"])
        reason = None
        if (row["language"] or "") in policy.excluded_languages:
            reason = "language"
        elif rule == "drop":
            reason = flag
        elif not any(c.isalnum() for c in key):
            reason = "empty"
        elif len(key) > policy.max_folded_length:
            reason = "long"
        elif key in own:
            reason = "canonical"
        elif rule == "guarded" and guard.get(guard_key(row["name"]), set()) - {
            row["city_id"]
        }:
            reason = "collision"
        elif key in kept:
            reason = "duplicate"
        if reason:
            dropped[reason] += 1
        else:
            kept[key] = row
    return sorted(kept.values(), key=lambda row: row["name"])


def grouped(rows: Iterable[Row]) -> Iterator[list[Row]]:
    current: list[Row] = []
    for row in rows:
        if current and row["city_id"] != current[0]["city_id"]:
            yield current
            current = []
        current.append(row)
    if current:
        yield current


def build(
    root: Path,
    output: Path,
    cities: list[Row],
    sources: dict[str, list[Row]],
    value: Row,
    resources: Resources,
    limits: EngineLimits,
) -> list[Path]:
    policy = parse(value)
    dropped: Counter[str] = Counter()
    sizes: list[int] = []
    db = query.connect(output / "spill", resources, limits)
    try:
        for kind in ("places", "canonical_cities", "place_to_city"):
            view(db, kind, [r for r in cities if r["kind"] == kind])
        own: dict[str, set[str]] = defaultdict(set)
        guard: dict[str, set[str]] = defaultdict(set)
        for city, *names in db.execute(
            "SELECT city_id, name, name_en FROM canonical_cities"
        ).fetchall():
            for name in filter(None, names):
                own[city].add(folded(name))
                guard[guard_key(name)].add(city)

        def rows() -> Iterator[Row]:
            for group in grouped(candidates(db, sources, policy)):
                city = group[0]["city_id"]
                selected = select(group, own[city], guard, policy, dropped)
                if selected:
                    sizes.append(len(selected))
                for row in selected:
                    yield {field.name: row[field.name] for field in SCHEMA}

        destination = output / "names.parquet"
        record = parquet(root, destination, rows(), SCHEMA, limits.parquet_batch_rows)
    finally:
        db.close()
    receipt = output / "names.json"
    write_json(
        receipt,
        {
            **record,
            "kind": "names",
            "cities": len(sizes),
            "max_per_city": max(sizes, default=0),
            "dropped": dict(sorted(dropped.items())),
        },
    )
    return [destination, receipt]
