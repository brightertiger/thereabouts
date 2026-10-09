"""The plate tables exactly as the pack writer reads them, with per-row licences."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

import pyarrow as pa

from pipeline.engines.artifact_io import parquet

from .documents import Pool
from .policy import Row


def strings(names: str, nullable: str = "") -> list[pa.Field[pa.DataType]]:
    optional = set(nullable.split())
    return [pa.field(n, pa.string(), n in optional) for n in names.split()]


def required(name: str, kind: pa.DataType) -> pa.Field[pa.DataType]:
    return pa.field(name, kind, False)


SCHEMAS: dict[str, pa.Schema] = {
    "plate_formats": pa.schema(
        [
            *strings(
                "country_code series_id series_status pattern relaxed_pattern "
                "code_group",
                "code_group",
            ),
            required("scripts", pa.list_(pa.string())),
            required("fixed_national_marks", pa.list_(pa.string())),
            required("specificity_bits", pa.float64()),
            *strings("provenance source source_file source_url license"),
        ]
    ),
    "plate_codes": pa.schema(
        [
            *strings(
                "country_code code name_en name_local unit_kind scope series_status "
                "series_id subdivision_scope",
                "name_en name_local series_id subdivision_scope",
            ),
            required("subdivision_codes", pa.list_(pa.string())),
            *strings("source source_url license"),
        ]
    ),
    "plate_policy": pa.schema(strings("policy_json")),
    "plate_priors": pa.schema(
        [
            *strings("country_code"),
            required("vehicles", pa.uint64()),
            required("year", pa.int64()),
            *strings("source_label source source_url license provenance"),
        ]
    ),
}


RULE_FIELDS = (
    "country_code",
    "series_id",
    "series_status",
    "pattern",
    "relaxed_pattern",
    "code_group",
    "scripts",
    "fixed_national_marks",
    "specificity_bits",
)


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def formats(rules: Iterable[Row], pins: Pool) -> Iterator[Row]:
    for rule in rules:
        provenance = rule["provenance"]
        yield {
            **{k: rule.get(k) for k in RULE_FIELDS},
            "provenance": encode(provenance),
            "source": pins.used[rule["source"]]["source"],
            "source_file": rule["source"],
            "source_url": provenance["url"],
            "license": provenance["license"],
        }


def codes(rows: Iterable[Row]) -> Iterator[Row]:
    for row in rows:
        value = row.get("subdivision_codes") or []
        yield {k: row.get(k) for k in SCHEMAS["plate_codes"].names} | {
            "subdivision_codes": json.loads(value) if isinstance(value, str) else value
        }


def priors(rows: Iterable[Row]) -> Iterator[Row]:
    for row in rows:
        provenance = row["provenance"]
        yield {
            **{k: row[k] for k in ("country_code", "vehicles", "year", "source_label")},
            "source": row["source"],
            "source_url": provenance["url"],
            "license": provenance["license"],
            "provenance": encode(provenance | {"locator": row["locator"]}),
        }


def policy(value: Row) -> Iterator[Row]:
    """The inference policy plus the Unicode decimal digits code equality maps."""
    zeroes = [n for n in range(0x110000) if unicodedata.decimal(chr(n), None) == 0]
    yield {
        "policy_json": encode(
            value
            | {
                "decimal_zeroes": zeroes,
                "decimal_unicode_version": unicodedata.unidata_version,
            }
        )
    }


def write(
    root: Path, output: Path, kind: str, rows: Iterable[Row], batch_rows: int
) -> Row:
    path = output / f"{kind}.parquet"
    return {**parquet(root, path, rows, SCHEMAS[kind], batch_rows), "kind": kind}
