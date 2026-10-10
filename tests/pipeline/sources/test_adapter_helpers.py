"""Shared adapter helpers reproduce each adapter's historical spelling exactly."""

import json
import math
import sqlite3
import unicodedata
from collections.abc import Callable, Iterator
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest

from pipeline.errors import ConfigError
from pipeline.runtime.jsonio import encode
from pipeline.runtime.ledger import Ledger
from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.rows import (
    RowRejected,
    canonical_json,
    clean_text,
    provenance,
)
from pipeline.sources.shared.scratch import scratch_index

from .fixtures import source_context

ACUTE, NBSP, EN_QUAD = chr(0x0301), chr(0x00A0), chr(0x2000)
TEXTS: list[object] = [
    None,
    "",
    "   ",
    f"  Cafe{ACUTE}\tPlace ",
    f"S{NBSP}Paulo",
    f"e{ACUTE}{EN_QUAD}x",
    f"e\t{ACUTE}",
    f"{ACUTE}e  ",
    "None",
    " null ",
    "NaN",
    "nan value",
    3,
    2.5,
]


# The cleaners as each adapter wrote them before the shared helper.
def geonames_text(value: str) -> str | None:
    return unicodedata.normalize("NFC", " ".join(value.split())) or None


def overture_text(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFC", str(value)).split())
    return result or None


def boundaries_text(value: object) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFC", str(value)).split())
    return result if result and result.lower() not in {"none", "null", "nan"} else None


@pytest.mark.parametrize("value", TEXTS)
def test_clean_text_reproduces_every_historical_cleaner(value: object) -> None:
    assert clean_text(value) == overture_text(value)
    assert clean_text(value, nulls={"none", "null", "nan"}) == boundaries_text(value)
    if isinstance(value, str):
        assert clean_text(value, order="split_first") == geonames_text(value)


def iso(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unexpected JSON value: {type(value)}")


VALUE = {"b": "café", "a": [1, 2.5, None, True], "c": {"z": "x", "y": "☃"}}
VARIANTS: list[tuple[Callable[[object], str], dict[str, Any]]] = [
    (lambda v: encode(v).decode(), {}),
    (
        lambda v: json.dumps(
            v, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ),
        {"sort_keys": False},
    ),
    (
        lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, allow_nan=False),
        {"separators": None},
    ),
    (
        lambda v: json.dumps(v, sort_keys=True, allow_nan=False),
        {"separators": None, "ensure_ascii": True},
    ),
    (
        lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":")),
        {"sort_keys": False, "allow_nan": True},
    ),
    (
        json.dumps,
        {
            "sort_keys": False,
            "separators": None,
            "ensure_ascii": True,
            "allow_nan": True,
        },
    ),
]


@pytest.mark.parametrize("variant", range(len(VARIANTS)))
def test_canonical_json_reproduces_every_historical_encoder(variant: int) -> None:
    reference, options = VARIANTS[variant]
    assert canonical_json(VALUE, **options) == reference(VALUE)
    if options.get("allow_nan"):
        assert canonical_json([math.nan], **options) == reference([math.nan])
    else:
        with pytest.raises(ValueError):
            canonical_json([math.nan], **options)


def test_canonical_json_default_handles_upstream_dates() -> None:
    value = {"when": datetime(2026, 1, 2, 3, 4, 5), "day": date(2026, 1, 2)}
    assert canonical_json(value, default=iso) == json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=iso,
    )
    with pytest.raises(TypeError):
        canonical_json(value)


def test_provenance_puts_licence_evidence_first_and_details_in_order() -> None:
    result = provenance(
        "https://example.test/source",
        "https://example.test/licence",
        "Contributors",
        {"retrieved_at": "2026-10-03", "raw": [1]},
        {"source_url": "https://example.test/override", "part": 2},
    )
    reference = {
        "source_url": "https://example.test/source",
        "license_url": "https://example.test/licence",
        "attribution": "Contributors",
        **{"retrieved_at": "2026-10-03", "raw": [1]},
        **{"source_url": "https://example.test/override", "part": 2},
    }
    assert list(result.items()) == list(reference.items())


def test_row_rejected_is_one_value_error_with_its_reason() -> None:
    error = RowRejected("empty source alias")
    assert isinstance(error, ValueError) and str(error) == "empty source alias"


@pytest.fixture
def source(tmp_path: Path) -> Iterator[SourceContext]:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        _, ctx, _ = source_context(
            tmp_path, ledger, "overture", {"divisions.parquet": (b"x", {})}
        )
        yield ctx


def test_scratch_index_publishes_a_checked_index_and_releases_its_bytes(
    source: SourceContext,
) -> None:
    with scratch_index(
        source, "entities.sqlite3", 10**8, label="Test", cache_kib=1024
    ) as index:
        index.db.execute("CREATE TABLE entities (id TEXT PRIMARY KEY)")
        with index.db:
            index.db.execute("INSERT INTO entities VALUES ('a')")
        assert index.db.execute("PRAGMA cache_size").fetchone() == (-1024,)
        assert index.db.execute("PRAGMA temp_store").fetchone() == (1,)
        index.check_size()
        assert not index.path.exists()
    assert index.path == source.work / source.inputs_hash / "entities.sqlite3"
    assert source.guard.reserved == 0
    assert source.guard.growth == index.path.stat().st_size
    with closing(sqlite3.connect(index.path)) as db:
        assert db.execute("SELECT id FROM entities").fetchall() == [("a",)]


def test_scratch_index_over_its_reservation_publishes_nothing(
    source: SourceContext,
) -> None:
    with (
        pytest.raises(ConfigError, match="Test index exceeds configured index_bytes"),
        scratch_index(
            source, "lookup.sqlite3", 1, label="Test", check="integrity_check"
        ) as index,
    ):
        index.db.execute("CREATE TABLE lookup (id INTEGER)")
        index.check_size()
    assert not (source.work / source.inputs_hash / "lookup.sqlite3").exists()
    assert (source.guard.reserved, source.guard.growth) == (0, 0)
