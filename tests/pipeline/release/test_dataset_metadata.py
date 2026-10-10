"""The dictionary metadata in config/dataset.yaml is anchored in code, not invented."""

import re
from typing import Any

import pytest

from pipeline.release.dataset_schema import check, load
from pipeline.release.tables import schema_description
from pipeline.runtime.fingerprints import REPOSITORY

DESCRIPTION = load(REPOSITORY / "config/dataset.yaml")

# A declared primary key must name the check that enforces or guarantees it.
ENFORCED_KEYS = {
    "places": "lookups gate duplicate_place_ids == 0; assembly rejects null keys",
    "canonical_cities": "one entry per anchor in the cities build; dangling == 0",
    "place_to_city": "normalize_cells fails if its join changes the row count",
    "cells": "stored descendants must equal the land cells (blocks.py); no nulls",
    "names": "the names engine keeps one row per city and folded name",
    "plate_priors": "the plate tables reject a repeated country, as the reader does",
    "blocks": "assembly writes one row per covered block; verify matches the index",
    # source_id names the source file and row; keys.py refuses a repeated key.
    "airports": "keys.py; measured unique on the 2026-10-02 world build",
    "postal_codes": "keys.py; measured unique on the 2026-10-02 world build",
    "ip_ranges": "keys.py; measured unique on the 2026-10-02 world build",
    "trade_locations": "keys.py; measured unique on the 2026-10-02 world build",
    "phone_metadata": "keys.py; measured unique on the 2026-10-02 world build",
    "phone_prefixes": "keys.py; measured unique on the 2026-10-02 world build",
    "timezone_cells": "keys.py; measured unique on the 2026-10-02 world build",
    "zone_tables": "keys.py; measured unique on the 2026-10-02 world build",
    "countries": "keys.py; the plate tables' country_code references need a key",
    "subdivisions": "keys.py; measured unique on the 2026-10-02 world build",
}

# Every reference the lookups integrity gates check (cells/metrics.py and
# normalize_cells/references.py) must be documented as a relationship.
GATED_REFERENCES = {
    ("cells", "country_id"),
    ("cells", "state_id"),
    ("cells", "city_id"),
    ("places", "parent_id"),
    ("places", "sovereign_id"),
    ("place_to_city", "city_id"),
    ("place_to_city", "place_id"),
    ("canonical_cities", "city_id"),
}


def present(value: Any, text: str) -> bool:
    quoted = re.search(rf"""["']{re.escape(str(value))}["']""", text) is not None
    listed = re.search(rf"(?m)^\s*-\s+{re.escape(str(value))}\s*$", text) is not None
    return quoted or listed


def test_the_metadata_passes_validation() -> None:
    check(DESCRIPTION)
    assert all(
        table["description"] and table["grain"] for table in DESCRIPTION.values()
    )


def test_a_released_manifest_embeds_the_metadata_without_repository_paths() -> None:
    released = schema_description(REPOSITORY / "config/dataset.yaml")
    assert set(released) == set(DESCRIPTION)
    for table, schema in released.items():
        assert schema["description"] and schema["grain"]
        for column, source in zip(
            schema["columns"], DESCRIPTION[table]["columns"], strict=True
        ):
            assert "values_from" not in column
            assert column.get("values") == source.get("values")


def test_every_enumeration_value_is_a_literal_in_its_declared_sources() -> None:
    checked = 0
    for table, schema in DESCRIPTION.items():
        for column in schema["columns"]:
            sources = column.get("values_from", [])
            texts = [(REPOSITORY / path).read_text() for path in sources]
            for item in column.get("values", []):
                checked += 1
                assert any(present(item["value"], text) for text in texts), (
                    f"{table}.{column['name']}: {item['value']!r} is not in {sources}"
                )
    assert checked > 60


def test_enumerations_declare_where_they_come_from() -> None:
    for table, schema in DESCRIPTION.items():
        for column in schema["columns"]:
            if "values" in column:
                assert column.get("values_from"), f"{table}.{column['name']}"


@pytest.mark.parametrize("table", sorted(DESCRIPTION))
def test_primary_keys_are_declared_only_where_they_are_guaranteed(table: str) -> None:
    keys = DESCRIPTION[table]["primary_key"]
    assert bool(keys) == (table in ENFORCED_KEYS)


def test_gated_references_are_documented_relationships() -> None:
    declared = {
        (table, column)
        for table, schema in DESCRIPTION.items()
        for relation in schema["relationships"]
        if relation["references"]["table"] == "places"
        for column in relation["columns"]
    }
    assert declared >= GATED_REFERENCES


def test_observation_tables_link_their_geography_to_places() -> None:
    for table in ("airports", "ip_ranges", "postal_codes", "trade_locations"):
        columns = {
            column
            for relation in DESCRIPTION[table]["relationships"]
            for column in relation["columns"]
        }
        assert columns == {"country_id", "state_id", "city_id"}
