"""The descriptive metadata beside each dataset column is validated when loaded."""

import copy
from pathlib import Path
from typing import Any

import pytest

from pipeline.release.dataset_schema import check, inputs, public

Description = dict[str, Any]


def small() -> Description:
    return {
        "parents": {
            "description": "Parent rows.",
            "grain": "One row per parent.",
            "primary_key": ["parent_id"],
            "relationships": [],
            "columns": [
                {
                    "name": "parent_id",
                    "type": "string",
                    "nullable": False,
                    "meaning": "Parent identifier",
                    "units": "none",
                },
                {
                    "name": "kind",
                    "type": "string",
                    "nullable": True,
                    "meaning": "Parent kind",
                    "units": "none",
                    "values": [
                        {"value": "big", "meaning": "A big parent"},
                        {"value": "small", "meaning": "A small parent"},
                    ],
                    "values_from": ["pipeline/release/dataset_schema.py"],
                },
            ],
        },
        "children": {
            "description": "Child rows.",
            "grain": "One row per child.",
            "primary_key": [],
            "relationships": [
                {
                    "columns": ["parent_id"],
                    "references": {"table": "parents", "columns": ["parent_id"]},
                    "meaning": "The owning parent",
                }
            ],
            "columns": [
                {
                    "name": "parent_id",
                    "type": "string",
                    "nullable": True,
                    "meaning": "Owning parent",
                    "units": "none",
                }
            ],
        },
    }


def broken(change: Any) -> Description:
    description = copy.deepcopy(small())
    change(description)
    return description


def test_a_small_valid_description_passes() -> None:
    check(small())


@pytest.mark.parametrize(
    ("message", "change"),
    [
        ("children: description", lambda d: d["children"].pop("description")),
        ("children: grain", lambda d: d["children"].update(grain=" ")),
        ("parents: unknown key", lambda d: d["parents"].update(descripton="typo")),
        (
            "parents.kind: unknown key",
            lambda d: d["parents"]["columns"][1].update(value="x"),
        ),
        ("primary key", lambda d: d["parents"].update(primary_key=["missing"])),
        (
            "unknown table",
            lambda d: d["children"]["relationships"][0]["references"].update(
                table="missing"
            ),
        ),
        (
            "unknown column",
            lambda d: d["children"]["relationships"][0].update(columns=["missing"]),
        ),
        (
            "arity",
            lambda d: d["children"]["relationships"][0].update(
                columns=["parent_id", "parent_id"]
            ),
        ),
        (
            "type",
            lambda d: d["parents"]["columns"][0].update(type="int64"),
        ),
        (
            "relationship meaning",
            lambda d: d["children"]["relationships"][0].update(meaning=""),
        ),
        (
            "duplicate",
            lambda d: d["parents"]["columns"][1]["values"].append(
                {"value": "big", "meaning": "again"}
            ),
        ),
        (
            "value meaning",
            lambda d: d["parents"]["columns"][1]["values"][0].update(meaning=""),
        ),
        (
            "value type",
            lambda d: d["parents"]["columns"][1]["values"][0].update(value=3),
        ),
        (
            "values_from requires values",
            lambda d: d["parents"]["columns"][0].update(values_from=["LICENSE"]),
        ),
        (
            "source file",
            lambda d: d["parents"]["columns"][1].update(values_from=["nowhere.py"]),
        ),
        (
            "parents: assembled must be a boolean",
            lambda d: d["parents"].update(assembled="yes"),
        ),
        (
            "parents.kind: assembled must be a boolean",
            lambda d: d["parents"]["columns"][1].update(assembled=1),
        ),
        (
            "parents: assembled columns must follow every input column",
            lambda d: d["parents"]["columns"][0].update(assembled=True),
        ),
        (
            "enumerations need",
            lambda d: d["parents"]["columns"][0].update(
                type="bool", values=[{"value": True, "meaning": "yes"}]
            ),
        ),
    ],
)
def test_each_violation_is_named(message: str, change: Any) -> None:
    with pytest.raises(ValueError, match=message):
        check(broken(change))


def test_sources_resolve_against_the_given_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source file"):
        check(small(), repository=tmp_path)


def test_public_schema_drops_repository_paths_and_changes_nothing_else() -> None:
    description = small()
    shown = public(description)
    kind = shown["parents"]["columns"][1]
    assert "values_from" not in kind and kind["values"] == [
        {"value": "big", "meaning": "A big parent"},
        {"value": "small", "meaning": "A small parent"},
    ]
    assert "values_from" in description["parents"]["columns"][1]
    assert shown["children"] == description["children"]


def test_inputs_leave_out_what_assembly_computes() -> None:
    description = small()
    description["parents"]["columns"].append(
        {
            "name": "derived",
            "type": "string",
            "nullable": False,
            "meaning": "Computed by assembly",
            "units": "none",
            "assembled": True,
        }
    )
    description["index"] = {
        **copy.deepcopy(small()["parents"]),
        "assembled": True,
        "relationships": [],
    }
    check(description)
    assert inputs(description) == small()
    assert [c["name"] for c in description["parents"]["columns"]][-1] == "derived"
