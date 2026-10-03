"""Retained source interpretation decisions using the new adapters."""

from pathlib import Path
from typing import Any

import pytest

from pipeline.runtime.jsonio import write_json
from pipeline.sources.plates import reader as plates_reader
from pipeline.sources.plates.html import Document
from pipeline.sources.plates.rules import list_rows, regex_rows
from pipeline.sources.plates.wikidata import rows as wikidata_rows


def test_section_prefixes_and_pdf_prose_keep_source_pairs() -> None:
    doc = Document(
        "<h2>Region (X)</h2><ul><li>A/B North</li>"
        "<li>C Former South until 1998</li></ul>"
    )
    parsed = list(
        list_rows(
            doc,
            dict(
                section_pattern="Region",
                code_prefix_section=r"\((?P<prefix>X)\)",
                item_pattern=r"(?P<codes>[A-Z/]+) (?P<name>.+)",
                code_pattern="[A-Z]",
                unit_kind="district",
                series_status="current",
                historic_pattern="Former",
                valid_to_pattern=r"until (?P<date>\d{4})",
            ),
        )
    )
    assert [r["code"] for r in parsed] == ["XA", "XB", "XC"]
    assert parsed[-1]["series_status"] == "historic"
    assert parsed[-1]["valid_to"] == "1998"
    rows = list(
        regex_rows(
            "HEADER North 01 South 402 END",
            dict(
                start="HEADER",
                stop="END",
                item_pattern=r"(?P<name>North|South) (?P<codes>\d{2,3})",
                code_pattern=r"\d+",
                unit_kind="district",
            ),
        )
    )
    assert [(r["code"], r["name_en"]) for r in rows] == [
        ("01", "North"),
        ("402", "South"),
    ]


def test_ordered_list_numbers_are_source_codes_and_nested_lists_do_not_reset() -> None:
    doc = Document(
        '<h2>Districts</h2><ol start="7"><li>North<ul><li>Note</li></ul></li>'
        '<li value="12">South</li><li>East</li></ol>'
    )
    rows = list(
        list_rows(
            doc,
            dict(
                parser="ordered_list",
                section_pattern="Districts",
                item_pattern=r"(?P<codes>\d+) (?P<name>.+)",
                code_pattern=r"\d+",
                unit_kind="district",
            ),
        )
    )
    assert [(r["code"], r["name_en"]) for r in rows] == [
        ("7", "North"),
        ("12", "South"),
        ("13", "East"),
    ]


def test_unknown_and_future_wikidata_dates_do_not_imply_historic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dated.json"
    values = [
        dict(item="http://www.wikidata.org/entity/Q2", statement="Q2-s", code="A"),
        dict(item="http://www.wikidata.org/entity/Q3", statement="Q3-s", code="B"),
    ]
    values[0].update(start="http://www.wikidata.org/.well-known/genid/some-value")
    values[1].update(end="2028-01-01T00:00:00Z")
    write_json(
        path,
        dict(
            results=dict(
                bindings=[{k: {"value": v} for k, v in r.items()} for r in values]
            )
        ),
    )
    parsed = list(wikidata_rows(path, "Q99", "2026-10-02"))
    assert parsed[0]["valid_from"] is None
    assert "genid/some-value" in parsed[0]["notes"]
    assert parsed[1]["valid_to"] == "2028-01-01T00:00:00Z"
    assert {r["series_status"] for r in parsed} == {"unknown"}


def test_amendment_suffixes_use_prefixes_from_referenced_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    countries = tmp_path / "countries.csv"
    countries.write_text("ISO3166-1-Alpha-2,CLDR display name,wikidata_id\n")
    rule = dict(
        parser="text",
        item_pattern=r"(?P<name>Vale County) adds (?P<codes>[A-Z, ]+)",
        code_pattern="[A-Z]{2}",
        unit_kind="county",
        series_status="current",
        prefix_source=dict(
            source="base.pdf",
            pattern=r"(?m)^  (?P<name>Vale) +(?P<prefixes>[A-Z], [A-Z])",
            code_pattern="[A-Z]",
        ),
    )
    policy = dict(rules={"amend.pdf": [rule]}, survey={}, formats={})
    text = {
        "base.pdf": "  NorthVale  R, S\n  Vale  X, Y\n",
        "amend.pdf": "Vale County adds AB, CD",
    }
    monkeypatch.setattr(plates_reader, "pdf_text", lambda path: text[path.name])
    files = {
        name: dict(
            path=str(tmp_path / name),
            kind="pdf",
            country_code="XY",
            url="https://example.invalid/" + name,
            sha256="a" * 64,
        )
        for name in text
    }
    files["countries.csv"] = dict(path=str(countries), kind="countries")
    rows = [r for kind, r, _ in plates_reader.records(dict(files=files), policy, 5)]
    assert {r["code"] for r in rows} == {"XAB", "YAB", "XCD", "YCD"}
    assert {r["name_en"] for r in rows} == {"Vale"}
    assert all(r["prefix_evidence"]["sha256"] == "a" * 64 for r in rows)


def test_wikidata_lists_expand_and_non_codes_are_audited(tmp_path: Path) -> None:
    path = tmp_path / "codes.json"
    bindings = [
        {
            "item": {"value": "http://www.wikidata.org/entity/Q2"},
            "statement": {"value": f"Q2-{i}"},
            "code": {"type": "literal", "value": value},
        }
        for i, value in enumerate(
            ["AB, CD", "https://example.invalid/image.png", "A...X"]
        )
    ]
    write_json(path, dict(results=dict(bindings=bindings)))
    rejected: list[dict[str, Any]] = []
    rows = list(wikidata_rows(path, "Q99", "2026-01-01", rejected=rejected))
    assert [r["code"] for r in rows] == ["AB", "CD"]
    assert len(rejected) == 2
    assert all(r["wikidata_id"] == "Q2" for r in rejected)
