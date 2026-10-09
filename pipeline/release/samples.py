"""Seeded queries, with the answers a released dataset requires of its packs.

Every query is a shared-vector request (`kind`, `values` and options, as in
`tests/fixtures/*-vectors.json`) and the expectation the dataset implies. The
same seed and dataset give the same queries, so acceptance reports are stable.
"""

import bisect
import itertools
import json
import random
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from re import _constants as constants  # type: ignore[attr-defined]
from re import _parser as parser  # type: ignore[attr-defined]
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.config.release import AcceptanceSettings
from pipeline.engines.artifacts import read_json
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import digest

from .source import Row

# The pack family that answers each check.
CHECKS = {
    "reverse": "core",
    "ocean": "core",
    "names": "core",
    "alternate_names": "core",
    "postal": "postal",
    "airports_iata": "airports",
    "airports_icao": "airports",
    "locode": "locode",
    "ip_v4": "ip",
    "ip_v6": "ip",
    "phone": "phone",
    "plates": "plates",
}
# Shared vector bundles over real data, by the family that answers them.
BUNDLES = {
    "core-sample": "core",
    "geocode": "core",
    "postal": "postal",
    "airports": "airports",
    "locode": "locode",
    "phone": "phone",
    "ip": "ip",
    "plates": "plates",
}
VECTORS = REPOSITORY / "tests/fixtures"
# Expected statuses that depend only on the query, never on the data loaded.
WORLD_SAFE = {"invalid_input", "unsupported_granularity"}
# Except these: "ZZ" is invalid only because the sample plates pack lacks it.
DATA_DEPENDENT = {"plate-033"}
GEOCODE_LIMIT = 100
PHONE_DIGITS = 12
NON_GEOGRAPHIC = "001"


@dataclass(frozen=True)
class Query:
    id: str
    check: str
    family: str
    request: Row
    expect: Row
    evidence: bool = True

    def job(self) -> Row:
        return {"id": self.id, "request": self.request, "evidence": self.evidence}


@dataclass(frozen=True)
class Where:
    """A row predicate over the named columns."""

    columns: tuple[str, ...]
    expression: Any


def present(name: str) -> Where:
    value = pc.field(name)
    return Where((name,), ~value.is_null() & (value != ""))


@dataclass
class Dataset:
    """Row access over a verified release directory through its manifest."""

    root: Path
    manifest: Row = field(init=False)

    def __post_init__(self) -> None:
        self.manifest = read_json(self.root / "manifest.json")

    def files(self, kind: str) -> list[Path]:
        return [
            self.root / table["path"]
            for table in self.manifest["tables"]
            if table["kind"] == kind
        ]

    def read(self, kind: str, columns: list[str], where: Any = None) -> pa.Table:
        parts = [
            pq.read_table(path, columns=columns, filters=where)
            for path in self.files(kind)
        ]
        if not parts:
            return pa.table({name: pa.array([], pa.string()) for name in columns})
        return pa.concat_tables(parts)

    def sample(
        self,
        kind: str,
        columns: list[str],
        count: int,
        rng: random.Random,
        where: Where | None = None,
    ) -> list[Row]:
        """`count` rows chosen uniformly among those `where` selects.

        Positions stay ranges or numpy arrays: a world cells table has 66 M rows.
        """
        paths = self.files(kind)
        eligible: list[Any] = []
        sizes = [0]
        for path in paths:
            with pq.ParquetFile(path) as file:
                total = file.metadata.num_rows
                if where is None:
                    eligible.append(None)
                    sizes.append(total)
                    continue
                table = file.read(columns=list(where.columns)).append_column(
                    "__row", pa.array(np.arange(total))
                )
                selected = table.filter(where.expression)["__row"].to_numpy()
                eligible.append(selected)
                sizes.append(len(selected))
        offsets = list(itertools.accumulate(sizes))
        picked = rng.sample(range(offsets[-1]), min(count, offsets[-1]))
        chosen: dict[int, list[int]] = defaultdict(list)
        for position in sorted(picked):
            number = bisect.bisect_right(offsets, position) - 1
            local = position - offsets[number]
            found = eligible[number]
            chosen[number].append(local if found is None else int(found[local]))
        result = []
        for number, rows in sorted(chosen.items()):
            result.extend(_rows(paths[number], sorted(rows), columns))
        return result


def _rows(path: Path, rows: list[int], columns: list[str]) -> list[Row]:
    """Read only the row groups holding `rows` (ascending file positions)."""
    result: list[Row] = []
    with pq.ParquetFile(path) as file:
        start = 0
        wanted = iter(rows)
        row = next(wanted, None)
        for group in range(file.metadata.num_row_groups):
            end = start + file.metadata.row_group(group).num_rows
            local = []
            while row is not None and row < end:
                local.append(row - start)
                row = next(wanted, None)
            if local:
                table = file.read_row_group(group, columns=columns)
                result.extend(table.take(local).to_pylist())
            start = end
    return result


def rng(settings: AcceptanceSettings, check: str) -> random.Random:
    return random.Random(f"{settings.seed}:{check}")


def reverse(data: Dataset, settings: AcceptanceSettings) -> list[Query]:
    rows = data.sample(
        "cells",
        ["h3_uint64", "country_id", "state_id", "city_id"],
        settings.land_cells,
        rng(settings, "reverse"),
    )
    queries = []
    for number, row in enumerate(rows):
        lat, lon = h3.cell_to_latlng(row["h3_uint64"])
        expect = {key: row[key] for key in ("country_id", "state_id", "city_id")}
        queries.append(
            Query(
                f"reverse-{number:05d}",
                "reverse",
                "core",
                {"kind": "coordinates", "values": [lat, lon]},
                {**expect, "cell": f"{row['h3_uint64']:x}"},
            )
        )
    return queries


def ocean(data: Dataset, settings: AcceptanceSettings) -> list[Query]:
    """Unstored resolution-8 cells inside covered blocks report no land."""
    stored: dict[str, tuple[Path, int]] = {}
    covered: set[str] = set()
    for table in data.manifest["tables"]:
        if table["kind"] != "cells":
            continue
        for block in table.get("blocks", []):
            stored[block["block"]] = (data.root / table["path"], block["row_group"])
        covered.update(table.get("empty_blocks", []))
    covered.update(stored)
    blocks = sorted(covered)
    if not blocks or not settings.ocean_points:
        return []
    random_ = rng(settings, "ocean")
    cache: dict[str, set[int]] = {}
    queries: list[Query] = []
    for _ in range(50 * settings.ocean_points):
        if len(queries) == settings.ocean_points:
            break
        block = random_.choice(blocks)
        parent = int(block, 16)
        size = h3.cell_to_children_size(parent, 8)
        cell = h3.child_pos_to_cell(parent, 8, random_.randrange(size))
        if block in stored:
            if block not in cache:
                path, group = stored[block]
                with pq.ParquetFile(path) as file:
                    keys = file.read_row_group(group, columns=["h3_uint64"])
                cache[block] = {int(key) for key in keys["h3_uint64"].to_numpy()}
            if any(h3.cell_to_parent(cell, r) in cache[block] for r in range(3, 9)):
                continue
        lat, lon = h3.cell_to_latlng(cell)
        queries.append(
            Query(
                f"ocean-{len(queries):05d}",
                "ocean",
                "core",
                {"kind": "coordinates", "values": [lat, lon]},
                {"status": "not_found", "reason": "no_land", "cell": f"{cell:x}"},
            )
        )
    return queries


def names(data: Dataset, settings: AcceptanceSettings) -> list[Query]:
    queries = []
    sources = (
        ("names", "canonical_cities", ["city_id", "name", "country_code"]),
        ("alternate_names", "names", ["city_id", "name", "country_code"]),
    )
    for check, kind, columns in sources:
        rows = data.sample(
            kind,
            columns,
            settings.names,
            rng(settings, check),
            where=present("name"),
        )
        for number, row in enumerate(rows):
            request = {
                "kind": "geocode",
                "values": [row["name"]],
                "country": row["country_code"],
                "limit": GEOCODE_LIMIT,
            }
            queries.append(
                Query(
                    f"{check}-{number:05d}",
                    check,
                    "core",
                    request,
                    {"city_id": row["city_id"]},
                )
            )
    return queries


def forward(
    data: Dataset, settings: AcceptanceSettings, families: set[str]
) -> list[Query]:
    """Observation rows found by their own key, answering their own places."""
    ids = ["country_id", "state_id", "city_id"]
    specs: list[tuple[str, str, str, Where | None, Callable[[Row], Row]]] = [
        (
            "postal",
            "postal_codes",
            "postal_code",
            present("postal_code"),
            lambda r: (
                {"kind": "postal", "values": [r["postal_code"]]}
                | {"country": r["country_code"]}
            ),
        ),
        (
            "airports_iata",
            "airports",
            "iata_code",
            present("iata_code"),
            lambda r: (
                {"kind": "airport", "values": [r["iata_code"]]} | {"scheme": "iata"}
            ),
        ),
        (
            "airports_icao",
            "airports",
            "icao_code",
            present("icao_code"),
            lambda r: (
                {"kind": "airport", "values": [r["icao_code"]]} | {"scheme": "icao"}
            ),
        ),
        (
            "locode",
            "trade_locations",
            "locode",
            None,
            lambda r: {"kind": "locode", "values": [r["locode"]]},
        ),
        (
            "ip_v4",
            "ip_ranges",
            "ip_start",
            Where(("ip_version",), pc.field("ip_version") == 4),
            lambda r: {"kind": "ip", "values": [r["ip_start"]]},
        ),
        (
            "ip_v6",
            "ip_ranges",
            "ip_start",
            Where(("ip_version",), pc.field("ip_version") == 6),
            lambda r: {"kind": "ip", "values": [r["ip_start"]]},
        ),
    ]
    sampled = []
    for check, kind, key, where, request in specs:
        if CHECKS[check] not in families:
            continue
        columns = sorted({key, "country_code", *ids})
        rows = data.sample(
            kind, columns, settings.forward_rows, rng(settings, check), where
        )
        sampled.append((check, rows, request))
    cities = canonical(data, {r["city_id"] for _, rows, _ in sampled for r in rows})
    queries = []
    for check, rows, request in sampled:
        for number, row in enumerate(rows):
            expect = {
                "country_id": row["country_id"],
                "state_id": row["state_id"],
                "city_id": cities.get(row["city_id"], row["city_id"]),
            }
            queries.append(
                Query(
                    f"{check}-{number:05d}",
                    check,
                    CHECKS[check],
                    request(row),
                    expect,
                )
            )
    return queries


def canonical(data: Dataset, cities: Iterable[str | None]) -> dict[str, str]:
    """The writer's forward association: a mapped place answers its city."""
    wanted = sorted(city for city in cities if city)
    if not wanted:
        return {}
    table = data.read(
        "place_to_city",
        ["place_id", "city_id"],
        where=pc.field("place_id").isin(wanted),
    )
    return {
        row["place_id"]: row["city_id"]
        for row in table.to_pylist()
        if row["city_id"] is not None
    }


def phone(data: Dataset, settings: AcceptanceSettings) -> list[Query]:
    """A number whose longest stored prefix is the sampled row's own prefix."""
    prefixes = {
        str(value)
        for kind, column in (
            ("phone_prefixes", "prefix"),
            ("phone_metadata", "calling_code"),
        )
        for value in data.read(kind, [column])[column].to_pylist()
        if value
    }
    rows = data.sample(
        "phone_prefixes",
        ["prefix", "country_codes"],
        3 * settings.forward_rows,
        rng(settings, "phone"),
    )
    queries: list[Query] = []
    for row in rows:
        countries = sorted(
            f"country:{code}"
            for code in row["country_codes"] or []
            if code != NON_GEOGRAPHIC
        )
        number = phone_number(row["prefix"], prefixes)
        if not countries or number is None:
            continue
        queries.append(
            Query(
                f"phone-{len(queries):05d}",
                "phone",
                "phone",
                {"kind": "phone", "values": [f"+{number}"]},
                {"countries": countries, "prefix": row["prefix"]},
            )
        )
        if len(queries) == settings.forward_rows:
            break
    return queries


def phone_number(prefix: str, prefixes: set[str]) -> str | None:
    for digit in "0123456789":
        number = prefix + digit * max(1, PHONE_DIGITS - len(prefix))
        # Only the number's own prefixes can be longer matches.
        longer = range(len(prefix) + 1, len(number) + 1)
        if not any(number[:length] in prefixes for length in longer):
            return number
    return None


def plates(data: Dataset, settings: AcceptanceSettings) -> list[Query]:
    """Registration codes inside a plate built from a same-series format."""
    formats: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in data.read(
        "plate_formats", ["country_code", "series_id", "pattern", "code_group"]
    ).to_pylist():
        if row["code_group"]:
            formats[(row["country_code"], row["series_id"])].append(row)
    rows = data.sample(
        "plate_codes",
        ["country_code", "code", "series_id"],
        3 * settings.forward_rows,
        rng(settings, "plates"),
    )
    queries: list[Query] = []
    for row in rows:
        series = [
            key
            for key in sorted(formats)
            if key[0] == row["country_code"]
            and (not row["series_id"] or key[1] == row["series_id"])
        ]
        for key in series:
            text = next(
                (
                    found
                    for rule in formats[key]
                    if (
                        found := synthesize(
                            rule["pattern"], rule["code_group"], row["code"]
                        )
                    )
                ),
                None,
            )
            if text is None:
                continue
            queries.append(
                Query(
                    f"plates-{len(queries):05d}",
                    "plates",
                    "plates",
                    {
                        "kind": "plate",
                        "values": [text],
                        "country": row["country_code"],
                        "series": key[1],
                    },
                    {"country": row["country_code"], "code": row["code"]},
                )
            )
            break
        if len(queries) == settings.forward_rows:
            break
    return queries


def synthesize(pattern: str, group: str, code: str) -> str | None:
    """The shortest text the pattern matches with `code` in its code group."""
    try:
        parsed = parser.parse(pattern)
        index = parsed.state.groupdict[group]
        text = "".join(_emit(list(parsed), index, code))
        found = re.fullmatch(pattern, text)
    except (re.error, KeyError, ValueError):
        return None
    return text if found is not None and found.group(group) == code else None


def _emit(items: list[Any], index: int, code: str) -> Iterable[str]:
    for op, value in items:
        if op is constants.LITERAL:
            yield chr(value)
        elif op is constants.IN:
            yield _member(value)
        elif op is constants.ANY:
            yield "A"
        elif op in (constants.MAX_REPEAT, constants.MIN_REPEAT):
            low, _, body = value
            for _ in range(low):
                yield from _emit(list(body), index, code)
        elif op is constants.SUBPATTERN:
            number, _, _, body = value
            if number == index:
                yield code
            else:
                yield from _emit(list(body), index, code)
        elif op is constants.BRANCH:
            yield from _emit(list(value[1][0]), index, code)
        elif op is constants.AT:
            continue
        else:
            raise ValueError(f"Unsupported pattern element: {op}")


def _member(items: list[Any]) -> str:
    for op, value in items:
        if op is constants.NEGATE:
            raise ValueError("Negated sets are not synthesized")
        if op is constants.LITERAL:
            return chr(value)
        if op is constants.RANGE:
            return chr(value[0])
        if op is constants.CATEGORY:
            return {
                constants.CATEGORY_DIGIT: "0",
                constants.CATEGORY_SPACE: " ",
                constants.CATEGORY_WORD: "A",
            }.get(value, "A")
    raise ValueError("Empty character set")


def vectors(families: Iterable[str]) -> list[Query]:
    """Shared vector cases whose expectations hold for any data (world-safe)."""
    wanted = set(families)
    queries = []
    for bundle, family in sorted(BUNDLES.items()):
        if family not in wanted:
            continue
        for case in json.loads((VECTORS / f"{bundle}-vectors.json").read_text())[
            "cases"
        ]:
            request, expected = case["request"], case["result"]
            if expected["status"] not in WORLD_SAFE or case["id"] in DATA_DEPENDENT:
                continue
            # Typed non-string values only exist at the library boundary.
            values = request["values"]
            if request["kind"] != "coordinates" and not isinstance(values[0], str):
                continue
            queries.append(
                Query(
                    f"vectors-{case['id']}",
                    "vectors",
                    family,
                    request,
                    {"result": expected},
                    evidence=False,
                )
            )
    return queries


def vectors_digest() -> str:
    return digest(
        {
            bundle: (VECTORS / f"{bundle}-vectors.json").read_text()
            for bundle in sorted(BUNDLES)
        }
    )


def queries(
    dataset: Path, settings: AcceptanceSettings, families: Iterable[str]
) -> list[Query]:
    """Every query the named families answer, in a stable order."""
    wanted = set(families)
    data = Dataset(dataset)
    result: list[Query] = []
    if "core" in wanted:
        result += reverse(data, settings) + ocean(data, settings)
        result += names(data, settings)
    result += forward(data, settings, wanted)
    if "phone" in wanted:
        result += phone(data, settings)
    if "plates" in wanted:
        result += plates(data, settings)
    return result + vectors(wanted)
