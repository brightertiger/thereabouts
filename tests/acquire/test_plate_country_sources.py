"""Small pinned-source, template and benchmark fixtures; no network."""

import re
from pathlib import Path

import pytest

from build_data.acquire.io import sha256_file, write_json
from build_data.plate_country import build, evaluation, formats, priors, sources
from build_data.plate_country.policy import Row
from build_data.plate_country.syntax import (
    relaxed_pattern,
    specificity,
    template_pattern,
)


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


def test_pins_cache_and_hash_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "raw" / "plates_country"
    raw.mkdir(parents=True)
    file = raw / "x.json"
    file.write_text("cached")
    config = {file.name: dict(sha256=sha256_file(file), download_url="unused")}
    monkeypatch.setattr(sources, "policy", lambda name: config)

    def no_fetch(*args: object, **kwargs: object) -> Row:
        pytest.fail("A cached source must not be fetched")

    monkeypatch.setattr(sources, "fetch", no_fetch)
    assert sources.pins(tmp_path, offline=False)[file.name]["path"] == str(file)
    file.write_text("changed")
    with pytest.raises(ValueError, match="hash differs"):
        sources.pins(tmp_path)
    file.unlink()
    with pytest.raises(FileNotFoundError, match="Missing pinned source"):
        sources.pins(tmp_path)


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
    monkeypatch.setattr(evaluation, "pins", lambda data: {"commons": pin})
    monkeypatch.setattr(evaluation, "policy", lambda name: [sample, sample])
    rows = evaluation.examples(tmp_path)
    assert len(rows) == 1 and rows[0]["plate"] == "AA-123"
    assert rows == evaluation.examples(tmp_path)
    sample["pattern"] = "MISSING"
    with pytest.raises(ValueError, match="Missing evaluation transcription"):
        evaluation.examples(tmp_path)


def test_status_rejects_changed_policy_even_when_bundle_did_not_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    write_json(config / "gaps.json", {"XY": "unverified"})
    monkeypatch.setattr(build, "DATA", config)
    monkeypatch.setattr(build, "pins", lambda data: {})
    monkeypatch.setattr(build, "load_manifest", lambda workspace, source: {})
    base = tmp_path / "normalized" / "plates" / "manifest.json"
    write_json(base, {})
    write_json(
        tmp_path / "normalized" / "plates_country" / "manifest.json",
        dict(**build.configuration(), base_manifest_sha256=sha256_file(base)),
    )
    build.verify(tmp_path)
    write_json(config / "gaps.json", {"XY": "new evidence"})
    with pytest.raises(ValueError, match="policies changed"):
        build.verify(tmp_path)
