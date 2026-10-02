"""Verify lookup schemas and recover methods from their recorded golden cell join."""

from collections.abc import Iterator
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq

from build_data.acquire.lookup_schemas import (
    LOOKUP_SCHEMAS,
    LookupKind,
    validate_lookup,
)
from build_data.golden.reader import Cells
from build_data.serve.snapshot import BATCH_ROWS, Row, Snapshot
from thereabouts.packs.jsonio import canonical, string
from thereabouts.packs.keys import country_code, key, normalize
from thereabouts.packs.layout import encode_flags

NORMALIZATION = {
    "postal": {
        "default": ["strip_ascii", "upper_ascii"],
        "countries": {
            country: ["strip_ascii", "upper_ascii", "remove_ascii_spaces"]
            for country in ("CA", "GB")
        },
    },
    "airports": {"default": ["strip_ascii", "upper_ascii"], "countries": {}},
}
SCHEMES = {
    "iata": "iata_code",
    "icao": "icao_code",
    "ident": "ident",
    "gps": "gps_code",
    "local": "local_code",
}
JOIN_FIELDS = [
    *[
        pa.field(name, pa.string())
        for name in (
            "country_id",
            "state_id",
            "city_id",
            "cell_country_code",
            "cell_status",
        )
    ],
    pa.field("country_disagrees", pa.bool_()),
]
REFS = ("country_id", "state_id", "city_id")


def schema(snapshot: Snapshot, family: str) -> list[Row]:
    kind: LookupKind = "postal_codes" if family == "postal" else "airports"
    tables = snapshot.tables(kind)
    if not tables:
        raise ValueError(f"Golden snapshot lacks {kind}")
    expected = pa.schema([*LOOKUP_SCHEMAS[kind], *JOIN_FIELDS])
    for table in tables:
        actual = pq.ParquetFile(snapshot.file(table)).schema_arrow
        if set(actual.names) != set(expected.names) or any(
            actual.field(f.name) != f for f in expected
        ):
            raise ValueError(f"Golden {kind} schema mismatch")
    return tables


def observation(row: Row, table: str, cells: Cells, family: str) -> Row:
    validate_lookup(row, "postal_codes" if family == "postal" else "airports")
    joined = cells.lookup(row["h3"])
    if joined["cell_status"] != row["cell_status"] or any(
        row[field] != joined.get(field) for field in REFS
    ):
        raise ValueError("Lookup assignments differ from their golden cell join")
    country = row["country_id"]
    code = None if country is None else country.removeprefix("country:")
    if row["cell_country_code"] != code:
        raise ValueError("Spatial country code disagrees with golden identity")
    expected = (
        None
        if row["country_code"] is None or code is None
        else row["country_code"] != code
    )
    if row["country_disagrees"] != expected:
        raise ValueError("Source-country disagreement is inconsistent")
    flags = 0
    if "h3" in joined:
        flags = encode_flags(
            joined["city_method"],
            joined["country_method"],
            joined["state_method"],
            joined["land_method"],
        )
    fields = dict(row)
    # JSON/JavaScript numbers cannot carry arbitrary uint64 values exactly.
    fields["h3_uint64"] = None if row["h3_uint64"] is None else str(row["h3_uint64"])
    reference = (
        None if row["h3"] is None else {"h3": row["h3"], "stored_h3": joined.get("h3")}
    )
    result: Row = {
        name: string(row[name])
        for name in ("source", "source_id", "source_release", "license")
    }
    result.update(
        golden_table=table,
        fields=fields,
        reference=reference,
        refs=[row[field] for field in REFS],
        flags=flags,
        cell_status=row["cell_status"],
        country_disagrees=row["country_disagrees"],
    )
    return result


def identity(row: Row, family: str) -> str:
    if family == "postal" and row["city_id"] is not None:
        return str(row["city_id"])
    prefix = "postal" if family == "postal" else "airport"
    return (
        prefix
        + ":"
        + quote(string(row["source"]), safe="")
        + ":"
        + quote(string(row["source_id"]), safe="")
    )


def keys(row: Row, family: str) -> list[str]:
    country = None if row["country_code"] is None else country_code(row["country_code"])
    rules = NORMALIZATION[family]
    if family == "postal":
        if country is None or not row["postal_code"]:
            return []
        return [
            key(family, normalize(row["postal_code"], rules, country), country, None)
        ]
    result = []
    for scheme, field in SCHEMES.items():
        if not row[field]:
            continue
        code = normalize(row[field], rules, country)
        if scheme != "local":
            result.append(key(family, code, None, scheme))
        if country is not None:
            result.append(key(family, code, country, scheme))
    return sorted(set(result), key=lambda value: value.encode("utf-8"))


def cells(snapshot: Snapshot) -> Cells:
    return Cells(
        [
            {**table, "path": str(snapshot.file(table))}
            for table in snapshot.tables("cells")
        ]
    )


def rows(snapshot: Snapshot, family: str) -> Iterator[tuple[str, Row]]:
    for table in schema(snapshot, family):
        for batch in pq.ParquetFile(snapshot.file(table)).iter_batches(
            batch_size=BATCH_ROWS
        ):
            for row in batch.to_pylist():
                canonical(row)  # Reject non-finite source evidence before publication.
                yield table["path"], row
