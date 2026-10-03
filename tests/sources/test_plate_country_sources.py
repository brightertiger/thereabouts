"""Small pinned-source, template and benchmark fixtures; no network."""

import re
from pathlib import Path

import pytest

from pipeline.engines.plate_country import formats, priors
from pipeline.engines.plate_country.policy import Row
from pipeline.engines.plate_country.syntax import (
    relaxed_pattern,
    specificity,
    template_pattern,
)
from pipeline.runtime.jsonio import sha256_file, write_json

from . import plate_evaluation as evaluation


def wiki(path: Path, html: str) -> Row:
    write_json(path, dict(parse=dict(revid=123, text={"*": html})))
    return dict(
        kind="wikipedia",
        path=str(path),
        revision=123,
        sha256=sha256_file(path),
        url="https://example.invalid/?oldid=123",
        license="CC0-1.0",
        retrieved_at="2026-01-01",
    )


def test_template_letters_are_slots_only_in_declared_dialect() -> None:
    assert template_pattern("T annn", "a-n") == r"T\ [A-Z][0-9][0-9][0-9]"
    assert template_pattern("ABC-123", "generic") == (
        r"[A-Z][A-Z][A-Z]\-[0-9][0-9][0-9]"
    )
    assert specificity("[0-9]{4}") > specificity("[A-Z]{4}")
    assert specificity("[0-9]{4}") == specificity("[0-9]{4,10}")
    assert "(?P<code>" in relaxed_pattern(r"(?P<code>[A-Z]{2})[ -]?[0-9]{3}")


def test_relaxed_regex_preserves_alternation_and_unicode_ranges() -> None:
    pattern = relaxed_pattern(r"(?:AB|CD)-[0-9]{3}")
    assert re.fullmatch(pattern, "AB123")
    assert re.fullmatch(pattern, "CD.123")
    assert re.fullmatch(pattern, "ABCD123") is None
    row = formats._decorate(dict(pattern=r"[\u0410-\u042f]{2}[0-9]{3}"), "fixture", {})
    assert row["separators"] == []
    assert row["scripts"] == ["ASCII digits", "Cyrillic"]


def test_formats_parse_only_pinned_evidence_and_fail_on_changed_cell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = wiki(
        tmp_path / "wiki.json",
        "<p>Prefix is district.</p><table>"
        "<tr><th>Region</th><th>Template</th></tr>"
        "<tr><td>North</td><td>AA 123</td></tr></table>",
    )
    table_rule = dict(
        country_code="XY",
        source="wiki",
        table=0,
        row=1,
        column=1,
        template="AA 123",
        placeholders="generic",
        series_id="current",
        series_status="current",
    )
    config = dict(formats=[], supplemental_formats=[], templates=[table_rule])
    monkeypatch.setattr(formats, "base_policy", lambda name: {})
    monkeypatch.setattr(formats, "policy", lambda name: config[name])
    rows = list(formats.rows({"wiki": pin}))
    assert rows[0]["evidence"] == "North | AA 123"
    assert rows[0]["provenance"]["sha256"] == pin["sha256"]
    table_rule["template"] = "BB 999"
    with pytest.raises(ValueError, match="Source template changed"):
        list(formats.rows({"wiki": pin}))


def test_prior_uses_actual_stock_not_per_capita_column_and_rejects_ambiguous_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin = wiki(
        tmp_path / "stock.json",
        "<table><tr><th>Country</th><th>Rate</th>"
        "<th>Vehicles</th><th>People</th><th>Year</th></tr>"
        "<tr><td>Example (note)</td><td>400</td><td>20,000</td>"
        "<td>50,000</td><td>2022</td></tr>"
        "<tr><td>Unknown</td><td>100</td><td>500</td>"
        "<td>5000</td><td>2020</td></tr>"
        "<tr><td>Example</td><td>400</td><td>estimated</td>"
        "<td>50,000</td><td>2023?</td></tr></table>",
    )
    monkeypatch.setattr(priors, "policy", lambda name: {})
    rows, rejected = priors.vehicle_rows(
        pin, [dict(country_code="XY", aliases=["Example"])]
    )
    assert len(rows) == 1 and rows[0]["vehicles"] == 20_000 and rows[0]["year"] == 2022
    assert len(rejected) == 2


def test_evaluation_extracts_source_text_deduplicates_and_keeps_split_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "commons.json"
    write_json(
        path,
        dict(
            query=dict(
                pages={
                    "7": dict(
                        title="File:Example AA-123 plate.jpg",
                        revisions=[dict(revid=9)],
                        imageinfo=[
                            dict(
                                url="https://example.invalid/photo",
                                sha1="unused",
                                extmetadata=dict(LicenseShortName=dict(value="CC0")),
                            )
                        ],
                    )
                }
            )
        ),
    )
    pin = dict(path=str(path), sha256=sha256_file(path))
    sample = dict(
        country_code="XY",
        source="commons",
        page_id=7,
        field="title",
        pattern=r"(?P<plate>AA-123)",
        method="source_transcription",
    )
    monkeypatch.setattr(evaluation, "policy", lambda name: [sample, sample])
    rows = evaluation.examples({"commons": pin})
    assert len(rows) == 1 and rows[0]["plate"] == "AA-123"
    assert rows == evaluation.examples({"commons": pin})
    sample["pattern"] = "MISSING"
    with pytest.raises(ValueError, match="Missing evaluation transcription"):
        evaluation.examples({"commons": pin})
