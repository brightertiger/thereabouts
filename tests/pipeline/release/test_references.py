"""Missing place keys are aliased, excluded or refused, and every change counted."""

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from pipeline.config import load
from pipeline.config.release import ClosureRules
from pipeline.release import closure, references
from pipeline.release.budget import Budget
from pipeline.release.dataset_schema import load as load_schema
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.resources import ResourceGuard

from .test_closure import closed, place, write

Row = dict[str, Any]
SCHEMA = load_schema(REPOSITORY / "config/dataset.yaml")
WORLD = ClosureRules(place_aliases={"country": {"AC": "SH", "TA": "SH"}})


def dataset() -> dict[str, list[Row]]:
    """The writer fixture, closed under every declared relationship."""
    tables = closed()
    tables["places"] = [
        row for row in tables["places"] if row["place_id"] != "district:lost"
    ]
    tables["places"].append(place("country:SH", "country", country_code="SH"))
    tables["names"][0]["place_id"] = "city:a"
    return tables


def resolve(
    root: Path, tables: dict[str, list[Row]], rules: ClosureRules
) -> tuple[list[references.Change], list[Row]]:
    config = load()
    records = write(root, tables)
    changes = references.plan(root, records, SCHEMA, rules)
    budget = Budget(10**9, ResourceGuard(root, config.resources))
    return changes, references.apply(
        root, records, changes, SCHEMA, config.release.dataset, budget
    )


def column(root: Path, kind: str, name: str) -> list[Any]:
    return pq.read_table(root / kind / "part.parquet", columns=[name])[name].to_pylist()


def summary(changes: list[references.Change]) -> list[tuple[Any, ...]]:
    return [(c.table, c.column, c.place, c.to, c.rows) for c in changes]


def test_a_closed_dataset_is_unchanged(tmp_path: Path) -> None:
    before = write(tmp_path / "before", dataset())
    changes, after = resolve(tmp_path / "after", dataset(), WORLD)
    assert changes == []
    assert [r["sha256"] for r in after] == [r["sha256"] for r in before]


def test_aliases_rewrite_codes_lists_and_ids(tmp_path: Path) -> None:
    tables = dataset()
    tables["phone_metadata"] = [
        {"source": "phone", "source_id": "1", "territory": "AC"},
        {"source": "phone", "source_id": "2", "territory": "001"},
    ]
    tables["phone_prefixes"] = [
        {"source_id": "1", "country_codes": ["SH", "TA"], "place_ids": []},
        {"source_id": "2", "country_codes": ["AC"], "place_ids": []},
        {"source_id": "3", "country_codes": ["AA", "001"], "place_ids": []},
    ]
    tables["postal_codes"].append({"country_id": "country:TA"})
    changes, records = resolve(tmp_path, tables, WORLD)
    assert summary(changes) == [
        ("phone_metadata", "territory", "country:AC", "country:SH", 1),
        ("phone_prefixes", "country_codes", "country:AC", "country:SH", 1),
        ("phone_prefixes", "country_codes", "country:TA", "country:SH", 1),
        ("postal_codes", "country_id", "country:TA", "country:SH", 1),
    ]
    assert column(tmp_path, "phone_metadata", "territory") == ["SH", "001"]
    # A list that already names the alias keeps one copy of it.
    assert column(tmp_path, "phone_prefixes", "country_codes") == [
        ["SH"],
        ["SH"],
        ["AA", "001"],
    ]
    assert column(tmp_path, "postal_codes", "country_id") == [
        "country:AA",
        "country:SH",
    ]
    rows = {r["kind"]: r["rows"] for r in records}
    assert (rows["phone_prefixes"], rows["postal_codes"]) == (3, 2)
    # Rewritten files are re-recorded and pass the pack writer's rules.
    assert references.plan(tmp_path, records, SCHEMA, WORLD) == []
    closure.check(tmp_path, records)


def test_excluded_places_drop_the_rows_that_refer_to_them(tmp_path: Path) -> None:
    tables = dataset()
    tables["postal_codes"] += [
        {"source_id": "2", "country_id": "country:ZZ"},
        {"source_id": "3", "country_id": "country:AA", "state_id": "state:zz"},
        {"source_id": "4", "country_id": "country:ZZ", "state_id": "state:zz"},
    ]
    rules = ClosureRules(
        excluded_places={"country": ["ZZ"], "state": ["zz"]},
    )
    changes, records = resolve(tmp_path, tables, rules)
    assert summary(changes) == [
        ("postal_codes", "country_id", "country:ZZ", None, 2),
        ("postal_codes", "state_id", "state:zz", None, 2),
    ]
    assert column(tmp_path, "postal_codes", "source_id") == [None]
    [record] = [r for r in records if r["kind"] == "postal_codes"]
    assert record["rows"] == 1
    assert pq.read_metadata(tmp_path / record["path"]).num_rows == 1


def test_unknown_places_can_exclude_every_unlisted_key(tmp_path: Path) -> None:
    tables = dataset()
    tables["airports"] = [
        {"source_id": "1", "state_id": "state:gone"},
        {"source_id": "2", "country_id": "country:AA"},
    ]
    changes, _ = resolve(tmp_path, tables, ClosureRules(unknown_places="exclude"))
    assert summary(changes) == [("airports", "state_id", "state:gone", None, 1)]
    assert column(tmp_path, "airports", "source_id") == ["2"]


def test_every_unlisted_missing_key_is_named(tmp_path: Path) -> None:
    tables = dataset()
    tables["phone_metadata"] = [{"source_id": "1", "territory": "AC"}]
    tables["phone_prefixes"][0]["country_codes"] = ["TA", "AC"]
    tables["postal_codes"][0]["state_id"] = "state:gone"
    with pytest.raises(ValueError) as error:
        resolve(tmp_path, tables, ClosureRules())
    assert str(error.value) == (
        "Dangling dataset place references; alias or exclude them in "
        "release.dataset.closure: phone_metadata.territory: country:AC; "
        "phone_prefixes.country_codes: country:AC, country:TA; "
        "postal_codes.state_id: state:gone"
    )


def test_an_alias_needs_an_existing_target(tmp_path: Path) -> None:
    tables = dataset()
    tables["places"] = [r for r in tables["places"] if r["place_id"] != "country:SH"]
    tables["phone_metadata"] = [{"source_id": "1", "territory": "AC"}]
    with pytest.raises(ValueError, match=r"alias target.*territory: country:AC"):
        resolve(tmp_path, tables, WORLD)


@pytest.mark.parametrize(
    ("kind", "change"),
    [
        ("cells", lambda t: t["cells"][0].update(city_id="city:gone")),
        ("places", lambda t: t["places"][2].update(parent_id="state:gone")),
        ("place_to_city", lambda t: t["place_to_city"][0].update(city_id="x:1")),
        (
            "canonical_cities",
            lambda t: t["canonical_cities"][0].update(place_id="city:gone"),
        ),
    ],
)
def test_indexed_and_referenced_rows_are_never_excluded(
    tmp_path: Path, kind: str, change: Any
) -> None:
    tables = dataset()
    change(tables)
    with pytest.raises(ValueError, match=f"cannot be excluded: {kind}\\."):
        resolve(tmp_path, tables, ClosureRules(unknown_places="exclude"))


def test_aliases_never_rewrite_an_existing_key(tmp_path: Path) -> None:
    tables = dataset()
    tables["places"].append(place("country:AC", "country", country_code="AC"))
    tables["phone_metadata"] = [{"source_id": "1", "territory": "AC"}]
    changes, _ = resolve(tmp_path, tables, WORLD)
    assert changes == []
    assert column(tmp_path, "phone_metadata", "territory") == ["AC"]


def test_plate_codes_must_name_a_country_row(tmp_path: Path) -> None:
    tables = dataset()
    tables["countries"] = [{"country_code": "SH", "country_id": "country:SH"}]
    tables["plate_formats"] = [{"country_code": "TA"}, {"country_code": "SH"}]
    changes, _ = resolve(tmp_path, tables, WORLD)
    assert summary(changes) == [
        ("plate_formats", "country_code", "country:TA", "country:SH", 1)
    ]
    assert column(tmp_path, "plate_formats", "country_code") == ["SH", "SH"]


def test_the_manifest_record_lists_every_change() -> None:
    changes = [
        references.Change("phone_metadata", "territory", "country:AC", "country:SH", 1),
        references.Change("postal_codes", "state_id", "state:zz", None, 2),
    ]
    assert references.record(WORLD, changes, {"places": 9, "reached": 7}) == {
        "unknown_places": "fail",
        "aliased": [
            {
                "table": "phone_metadata",
                "column": "territory",
                "place": "country:AC",
                "to": "country:SH",
                "rows": 1,
            }
        ],
        "excluded": [
            {
                "table": "postal_codes",
                "column": "state_id",
                "place": "state:zz",
                "rows": 2,
            }
        ],
        "places": 9,
        "reached": 7,
    }
