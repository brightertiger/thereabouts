"""The dataset refuses every place reference the pack writer would refuse."""

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.engines.artifact_io import file_record
from pipeline.release import closure
from pipeline.release.dataset_schema import load
from pipeline.runtime.fingerprints import REPOSITORY
from tests.skill.dataset import DEFAULTS, arrow_type

Row = dict[str, Any]
SCHEMA = load(REPOSITORY / "config/dataset.yaml")


def place(identifier: str, role: str, **more: Any) -> Row:
    return {
        "place_id": identifier,
        "role": role,
        "country_code": "AA",
        "normalized_city_id": identifier if role == "city" else None,
        **more,
    }


def closed() -> dict[str, list[Row]]:
    return {
        "places": [
            place("country:AA", "country"),
            place("state:aa", "state", parent_id="country:AA"),
            place("city:a", "city", parent_id="state:aa"),
            place("district:d", "district", parent_id="city:a"),
            # Unreached by any seed: the writer never resolves its parent.
            place("district:lost", "district", parent_id="district:gone"),
        ],
        "canonical_cities": [{"city_id": "city:a", "place_id": "city:a"}],
        "place_to_city": [{"place_id": "city:a", "city_id": "city:a"}],
        "cells": [
            {
                "h3_uint64": 0x8830E1D8C7FFFFF,
                "country_id": "country:AA",
                "state_id": "state:aa",
                "city_id": "city:a",
            }
        ],
        "names": [{"city_id": "city:a", "name": "Alpha", "kind": "alternate"}],
        "postal_codes": [{"country_id": "country:AA", "city_id": "district:d"}],
        "phone_prefixes": [{"country_codes": ["AA", "001"], "place_ids": []}],
    }


def write(root: Path, tables: dict[str, list[Row]]) -> list[Row]:
    records = []
    for kind, rows in tables.items():
        columns = SCHEMA[kind]["columns"]
        schema = pa.schema(
            pa.field(c["name"], arrow_type(c["type"]), nullable=c["nullable"])
            for c in columns
        )
        defaults = {
            c["name"]: DEFAULTS[c["type"]] for c in columns if not c["nullable"]
        }
        path = root / kind / "part.parquet"
        path.parent.mkdir(parents=True)
        pq.write_table(
            pa.Table.from_pylist([defaults | row for row in rows], schema=schema), path
        )
        records.append({**file_record(root, path), "kind": kind, "rows": len(rows)})
    return records


def test_a_closed_dataset_passes(tmp_path: Path) -> None:
    summary = closure.check(tmp_path, write(tmp_path, closed()))
    # Seeds plus their parents; the unreached district and its parent are not.
    assert summary == {"places": 5, "reached": 4}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda t: t["cells"][0].update(city_id="city:missing"),
            "Dangling dataset place reference: city:missing",
        ),
        (
            lambda t: t["places"][1].update(parent_id="country:ZZ"),
            "Dangling dataset place reference: country:ZZ",
        ),
        (
            lambda t: t["places"].append(place("city:a", "town")),
            "Duplicate place ID: city:a",
        ),
        (
            lambda t: t["places"][0].update(country_code=None),
            "Place lacks a country code: country:AA",
        ),
        (
            lambda t: t["place_to_city"][0].update(city_id="state:aa"),
            "Place mapping disagrees with catalogue: city:a",
        ),
        (
            lambda t: t["names"][0].update(city_id="state:aa"),
            "Name references a noncanonical city: state:aa",
        ),
        (
            lambda t: t["phone_prefixes"][0].update(country_codes=["BB", "001"]),
            "Dangling dataset place reference: country:BB",
        ),
        (
            lambda t: t["postal_codes"][0].update(state_id="state:gone"),
            "Dangling dataset place reference: state:gone",
        ),
        (
            lambda t: t["phone_prefixes"][0].update(place_ids=["city:gone"]),
            "Dangling dataset place reference: city:gone",
        ),
        (
            lambda t: t["canonical_cities"].append(
                {"city_id": "city:ghost", "place_id": "city:ghost"}
            ),
            "Dangling dataset place reference: city:ghost",
        ),
    ],
)
def test_the_writer_rules_are_refused(
    tmp_path: Path, change: Any, message: str
) -> None:
    tables = closed()
    change(tables)
    with pytest.raises(ValueError, match=message):
        closure.check(tmp_path, write(tmp_path, tables))


def test_self_normalized_places_are_seeds(tmp_path: Path) -> None:
    tables = closed()
    tables["places"].append(
        place("village:v", "village", normalized_city_id="village:v", parent_id="x:1")
    )
    with pytest.raises(ValueError, match="Dangling dataset place reference: x:1"):
        closure.check(tmp_path, write(tmp_path, tables))


def test_every_dangling_reference_is_named(tmp_path: Path) -> None:
    tables = closed()
    tables["cells"][0].update(city_id="city:missing")
    tables["postal_codes"][0].update(state_id="state:gone")
    with pytest.raises(ValueError) as error:
        closure.check(tmp_path, write(tmp_path, tables))
    assert str(error.value) == (
        "Dangling dataset place reference: city:missing, state:gone"
    )
