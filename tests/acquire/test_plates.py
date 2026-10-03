"""Retained source interpretation decisions using the new adapters."""

import json
from pathlib import Path

import pytest

from pipeline.runtime.jsonio import write_json
from pipeline.sources.plates.html import Document
from pipeline.sources.plates.rules import codes, evidence, table_rows
from pipeline.sources.plates.text import fixed_rows
from pipeline.sources.plates.wikidata import rows as wikidata_rows
from pipeline.sources.shared.plates_validation import validate_plate


def test_spans_keep_shared_codes_and_do_not_drop_row_headers() -> None:
    doc = Document(
        "<h2>Regions</h2><table><tr><th>Code</th><th>Place</th></tr>"
        '<tr><th rowspan="2">XY</th><td>North</td></tr>'
        "<tr><td>South</td></tr><tr><td>Z, ZZ</td><td>East</td></tr></table>"
    )
    parsed = list(
        table_rows(
            doc,
            dict(
                tables=[0],
                pairs=[[0, 1]],
                code_pattern=r"\b[A-Z]{1,2}\b",
                unit_kind="district",
                series_status="current",
                header_contains="Place",
            ),
        )
    )
    assert [(r["code"], r["name_en"]) for r in parsed] == [
        ("XY", "North"),
        ("XY", "South"),
        ("Z", "East"),
        ("ZZ", "East"),
    ]
    with pytest.raises(ValueError, match="Evidence not found"):
        evidence(doc, "a statement that was not fetched")


def test_ranges_are_opt_in_and_preserve_leading_zeroes() -> None:
    rule = dict(code_pattern=r"\b\d{2}\b", numeric_ranges=True, max_numeric_range=1000)
    assert codes("01-03, 08", rule) == ["01", "02", "03", "08"]
    assert codes("01-03", dict(code_pattern=r"\b\d{2}\b")) == ["01", "03"]
    assert codes("NONE XY", dict(code_pattern="[A-Z]+", code_exclude="NONE")) == ["XY"]
    assert codes(
        "AH-AK",
        dict(
            code_pattern=r"\b[A-Z]{2}\b",
            alpha_ranges=True,
            max_alpha_range=1000,
            excluded_letters="I",
        ),
    ) == ["AH", "AJ", "AK"]
    with pytest.raises(ValueError, match="Invalid"):
        codes("08-01", rule)


def test_fixed_columns_continuations_ranges_and_exceptions() -> None:
    text = "START\nWest      AH-AK\n          AL\n(AL only for Island)\nSTOP"
    rule = dict(
        start="START",
        stop="STOP",
        name_slice=[0, 10],
        code_start=10,
        code_line_pattern=r"[A-Z -]+",
        code_pattern=r"\b[A-Z]{2}\b",
        alpha_ranges=True,
        max_alpha_range=1000,
        excluded_letters="I",
        series_id="test",
        series_status="current",
        unit_kind="office",
        exceptions=[r"\((?P<code>AL) only for (?P<name>Island)\)"],
    )
    parsed = list(fixed_rows(text, rule))
    assert [(r["code"], r["name_en"]) for r in parsed] == [
        ("AH", "West"),
        ("AJ", "West"),
        ("AK", "West"),
        ("AL", "Island"),
    ]


def test_wikidata_cross_products_merge_but_do_not_imply_current(tmp_path: Path) -> None:
    base = {
        k: {"value": v}
        for k, v in dict(
            item="http://www.wikidata.org/entity/Q1",
            code="007",
            statement="http://www.wikidata.org/entity/statement/Q1-x",
            name_en="North",
            coord="Point(10 20)",
        ).items()
    }
    records = [
        {**base, "type": {"value": f"http://www.wikidata.org/entity/Q{i}"}}
        for i in (10, 11)
    ]
    path = tmp_path / "query.json"
    write_json(path, dict(results=dict(bindings=records)))
    parsed = list(wikidata_rows(path, "Q99", "2026-01-01"))
    assert len(parsed) == 1 and parsed[0]["series_status"] == "unknown"
    assert parsed[0]["latitude"] == 20 and parsed[0]["longitude"] == 10
    assert parsed[0]["code"] == "007"
    assert json.loads(parsed[0]["entity_types"]) == ["Q10", "Q11"]
    assert list(wikidata_rows(path, "Q1", "2026-01-01")) == []


def test_format_rejects_missing_capture_and_bad_specimens() -> None:
    row = dict(
        country_code="XY",
        source_url="https://example.invalid",
        retrieved_at="today",
        series_status="current",
        pattern=r"[A-Z]{2}\d{3}",
        code_group="code",
        examples=[],
    )
    with pytest.raises(ValueError, match="capture"):
        validate_plate(row, "plate_formats")
    row.update(pattern=r"(?P<code>[A-Z]{2})\d{3}", examples=["XY12"])
    with pytest.raises(ValueError, match="specimen"):
        validate_plate(row, "plate_formats")
