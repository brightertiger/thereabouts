"""Facts the dictionary derives from the Rust core and the Python client."""

import pytest
import yaml

from pipeline.release.tables import schema_description
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.tools import dictionary_surface as surface

RESULT = REPOSITORY / "core/thereabouts-core/src/result.rs"
TOOLS = {"reverse", "h3", "geocode", "postal", "airport", "locode"} | {
    "phone",
    "ip",
    "plate",
    "describe",
}


def api() -> dict[str, object]:
    value = yaml.safe_load((REPOSITORY / "config/api.yaml").read_text())
    assert isinstance(value, dict)
    return value


def test_status_kind_and_match_come_from_the_rust_enums() -> None:
    status = surface.rust_enum(RESULT, "Status")
    assert [item["value"] for item in status] == [
        "matched",
        "ambiguous",
        "not_found",
        "invalid_input",
        "unsupported_granularity",
    ]
    assert status[0]["meaning"] == "Published geography or one resolved place"
    assert "nearest_distant" in [i["value"] for i in surface.rust_enum(RESULT, "Match")]
    assert len(surface.rust_enum(RESULT, "Kind")) == 8


def test_an_unknown_enum_is_an_error() -> None:
    with pytest.raises(ValueError, match="Nothing"):
        surface.rust_enum(RESULT, "Nothing")


def test_struct_fields_carry_their_doc_comments() -> None:
    fields = surface.rust_struct(RESULT, "LookupResult")
    assert fields["match"].startswith("Published spatial method")
    assert fields["evidence"].startswith("Opt-in audit fields")
    assert "reason" in surface.rust_struct(RESULT, "Evidence")


def test_the_tools_are_read_from_the_server() -> None:
    tools = {tool["name"]: tool for tool in surface.mcp_tools()}
    assert set(tools) == TOOLS
    reverse = {p["name"]: p for p in tools["reverse"]["parameters"]}
    assert reverse["lat"]["required"] and reverse["lat"]["type"] == "number"
    assert (
        not reverse["evidence"]["required"] and reverse["evidence"]["default"] is False
    )
    assert tools["geocode"]["parameters"][1]["type"] == "string or null"
    assert all(tool["read_only"] for tool in tools.values())
    assert all(p["description"] for t in tools.values() for p in t["parameters"])


def test_resources_are_listed() -> None:
    uris = {item["uri"] for item in surface.mcp_resources()}
    assert uris == {"thereabouts://dictionary", "thereabouts://dictionary/markdown"}


def test_result_shape_joins_python_fields_with_rust_docs() -> None:
    shape = surface.result_shape(REPOSITORY)
    fields = {f["name"]: f for f in shape["fields"]}
    assert fields["status"]["type"] == "string"
    assert fields["candidates"]["type"] == "array of Result"
    assert fields["city"]["type"] == "City or null"
    assert fields["status"]["meaning"].startswith("Typed outcome")
    assert {"Country", "State", "City", "Point", "DistanceBand", "Evidence"} == set(
        shape["objects"]
    )
    evidence = {f["name"]: f for f in shape["objects"]["Evidence"]}
    assert evidence["timezones"]["type"] == "array of string"
    assert evidence["source_ids"]["type"] == "array of objects or null"


def test_error_codes_include_the_stable_strings() -> None:
    codes = {item["code"]: item["meaning"] for item in surface.error_codes()}
    assert "data_not_installed" in codes and "closed_geocoder" in codes
    assert all(codes.values())


def test_every_evidence_reason_and_rank_basis_is_spelled_in_its_source() -> None:
    vocabularies = api()["vocabularies"]
    assert isinstance(vocabularies, dict)
    for name in ("evidence_reason", "rank_basis"):
        for item in vocabularies[name]["values"]:
            text = (REPOSITORY / item["source"]).read_text()
            assert f'"{item["value"]}"' in text, (name, item["value"])


def test_families_match_the_supported_set_and_the_schema() -> None:
    from pipeline.config.release import PACK_FAMILIES

    families = api()["families"]
    assert isinstance(families, dict)
    assert tuple(families) == PACK_FAMILIES
    tables = schema_description(REPOSITORY / "config/dataset.yaml")
    for family in families.values():
        assert set(family["tables"]) <= set(tables)
        assert set(family["tools"]) <= TOOLS
    assert {t for f in families.values() for t in f["tools"]} == TOOLS - {"describe"}


def test_tool_descriptions_name_the_pack_they_need() -> None:
    from pipeline.tools import dictionary

    for tool in dictionary.build()["tools"]:
        if tool["pack"]:
            assert f"Needs the {tool['pack']} pack" in tool["description"], tool["name"]


def test_a_missing_mcp_extra_is_an_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.delitem(sys.modules, "thereabouts.mcp_service.server")
    monkeypatch.setitem(sys.modules, "mcp.server", None)
    with pytest.raises(ValueError, match="uv sync --all-extras"):
        surface.mcp_tools()
