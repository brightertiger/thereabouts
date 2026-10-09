"""Acceptance queries are seeded, drawn from the dataset and checkable by design."""

import re
from dataclasses import replace
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from h3.api import basic_int as h3

from pipeline.config import load
from pipeline.config.release import AcceptanceSettings
from pipeline.release import samples
from tests.skill.dataset import ARRONDISSEMENT, PARIS

from .synthetic import dataset as synthetic_dataset

FAMILIES = ("core", "postal", "airports", "locode", "phone", "ip", "plates")


@pytest.fixture(scope="module")
def dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return synthetic_dataset(tmp_path_factory.mktemp("samples"))[0]


@pytest.fixture
def settings() -> AcceptanceSettings:
    return replace(load().release.acceptance, ocean_points=50)


def test_the_same_seed_gives_the_same_queries(
    dataset: Path, settings: AcceptanceSettings
) -> None:
    first = samples.queries(dataset, settings, FAMILIES)
    assert first == samples.queries(dataset, settings, FAMILIES)
    other = samples.queries(dataset, replace(settings, seed=1), FAMILIES)
    assert [q.request for q in other if q.check == "ocean"] != [
        q.request for q in first if q.check == "ocean"
    ]
    checks = {q.check for q in first}
    assert checks == set(samples.CHECKS) | {"vectors"}


def test_reverse_expectations_are_the_stored_rows(
    dataset: Path, settings: AcceptanceSettings
) -> None:
    rows = {
        f"{row['h3_uint64']:x}": row
        for path in (dataset / "cells").glob("**/*.parquet")
        for row in pq.read_table(path).to_pylist()
    }
    reverse = [
        q for q in samples.queries(dataset, settings, ["core"]) if q.check == "reverse"
    ]
    assert len(reverse) == len(rows)
    for query in reverse:
        row = rows[query.expect["cell"]]
        assert {k: row[k] for k in ("country_id", "state_id", "city_id")} == {
            k: query.expect[k] for k in ("country_id", "state_id", "city_id")
        }
        lat, lon = query.request["values"]
        cell = h3.latlng_to_cell(lat, lon, 8)
        assert (
            h3.cell_to_parent(cell, h3.get_resolution(row["h3_uint64"]))
            == row["h3_uint64"]
        )


def test_ocean_points_are_never_stored(
    dataset: Path, settings: AcceptanceSettings
) -> None:
    stored = {
        row["h3_uint64"]
        for path in (dataset / "cells").glob("**/*.parquet")
        for row in pq.read_table(path, columns=["h3_uint64"]).to_pylist()
    }
    ocean = [
        q for q in samples.queries(dataset, settings, ["core"]) if q.check == "ocean"
    ]
    assert len(ocean) == 50
    for query in ocean:
        cell = h3.latlng_to_cell(*query.request["values"], 8)
        assert not {h3.cell_to_parent(cell, r) for r in range(3, 9)} & stored


def test_forward_cities_follow_the_writer_association(dataset: Path) -> None:
    data = samples.Dataset(dataset)
    assert samples.canonical(data, {ARRONDISSEMENT, PARIS, None}) == {
        ARRONDISSEMENT: PARIS,
        PARIS: PARIS,
    }


def test_families_select_their_own_checks(
    dataset: Path, settings: AcceptanceSettings
) -> None:
    postal = samples.queries(dataset, settings, ["postal"])
    assert {q.family for q in postal} == {"postal"}
    assert {q.check for q in postal} == {"postal", "vectors"}


def test_phone_numbers_avoid_longer_stored_prefixes() -> None:
    assert samples.phone_number("1", {"1", "12", "10"}) == "111111111111"
    assert samples.phone_number("32", {"32"}) == "320000000000"
    assert samples.phone_number("1", {f"1{d}" for d in "0123456789"}) is None


def test_plates_are_synthesized_inside_their_pattern() -> None:
    pattern = "[A-Z]{2}-[0-9]{3}-[A-Z]{2} (?P<code>[0-9]{2})"
    assert samples.synthesize(pattern, "code", "75") == "AA-000-AA 75"
    assert samples.synthesize(pattern, "code", "7A") is None
    assert samples.synthesize("(?P<code>[A-Z]{2})(?:-| )[0-9]+", "code", "MH") == (
        "MH-0"
    )
    assert samples.synthesize(r"\p{Lu}(?P<code>1)", "code", "1") is None
    assert samples.synthesize("[^A](?P<code>1)", "code", "1") is None


def test_vectors_are_the_world_safe_cases() -> None:
    queries = samples.vectors(FAMILIES)
    assert len(queries) > 40
    assert {q.expect["result"]["status"] for q in queries} <= samples.WORLD_SAFE
    assert all(not q.evidence for q in queries)
    assert all(re.fullmatch(r"vectors-\S+", q.id) for q in queries)
    assert len({q.id for q in queries}) == len(queries)
