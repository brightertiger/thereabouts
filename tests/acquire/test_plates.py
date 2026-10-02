"""Synthetic geographic evidence, no network or live plate data."""

import json
from pathlib import Path
from typing import Any

import pytest

from build_data.acquire import Workspace, plates, plates_config, plates_normalize
from build_data.acquire.io import sha256_file, write_json
from build_data.acquire.manifests import load_manifest
from build_data.acquire.plates_html import Document
from build_data.acquire.plates_reader import records
from build_data.acquire.plates_rules import codes, evidence, table_rows
from build_data.acquire.plates_text import fixed_rows
from build_data.acquire.plates_validation import validate_plate
from build_data.acquire.plates_wikidata import rows as wikidata_rows
from build_data.acquire.status import source_status


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
    rule = dict(code_pattern=r"\b\d{2}\b", numeric_ranges=True)
    assert codes("01-03, 08", rule) == ["01", "02", "03", "08"]
    assert codes("01-03", dict(code_pattern=r"\b\d{2}\b")) == ["01", "03"]
    assert codes("NONE XY", dict(code_pattern="[A-Z]+", code_exclude="NONE")) == ["XY"]
    assert codes(
        "AH-AK",
        dict(code_pattern=r"\b[A-Z]{2}\b", alpha_ranges=True, excluded_letters="I"),
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


@pytest.fixture
def plate_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.setattr(Workspace, "check_budget", lambda self, required_bytes=0: None)
    workspace = Workspace(tmp_path / "data")
    workspace.prepare()
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(plates_config, "DATA", config)
    monkeypatch.setattr(plates_normalize, "DATA", config)
    raw = workspace.raw("plates") / "research"
    raw.mkdir()
    (raw / "countries.csv").write_text(
        "ISO3166-1-Alpha-2,CLDR display name,wikidata_id\nXY,Example,https://www.wikidata.org/wiki/Q99\n"
    )
    write_json(
        raw / "wiki-XY.json",
        dict(
            parse=dict(
                revid=1,
                text={
                    "*": "<p>The prefix identifies the district.</p>"
                    "<table><tr><th>Code</th><th>Place</th></tr>"
                    "<tr><th>AA</th><td>North</td></tr></table>"
                },
            )
        ),
    )
    sources = {
        p.name: dict(
            kind="countries" if p.suffix == ".csv" else "wikipedia",
            country_code="XY",
            revision=1,
            url="https://example.invalid/source",
            download_url="https://example.invalid/source",
            size=p.stat().st_size,
            sha256=sha256_file(p),
            license="CC0-1.0",
            license_url="https://example.invalid/license",
            attribution="Synthetic fixture",
            retrieved_at="today",
        )
        for p in raw.iterdir()
    }
    write_json(config / "sources.json", sources)
    write_json(
        config / "rules.json",
        {
            "wiki-XY.json": [
                dict(
                    parser="table",
                    tables=[0],
                    pairs=[[0, 1]],
                    code_pattern="[A-Z]{2}",
                    unit_kind="district",
                    series_status="current",
                )
            ]
        },
    )
    write_json(
        config / "survey.json",
        {
            "XY": dict(
                source="wiki-XY.json",
                classification="usable_now",
                unit_kind="district",
                code_position="prefix",
                evidence_pattern="The prefix identifies the district",
            )
        },
    )
    write_json(config / "formats.json", {})
    write_json(config / "coverage.json", {})
    write_json(config / "wikidata.json", {})
    return workspace


def test_offline_publication_resume_and_corruption(
    plate_workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    plates.download(plate_workspace)
    plates.normalize(plate_workspace)
    manifest = load_manifest(plate_workspace, "plates")
    assert manifest["rows"] == {"plate_codes": 1, "plate_survey": 1}
    assert source_status(plate_workspace, "plates")["normalize"] == "complete"
    before = {
        p: p.stat().st_mtime_ns for p in plate_workspace.root.rglob("*") if p.is_file()
    }
    reader = records

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Completed normalization must not parse again")

    monkeypatch.setattr(plates_normalize, "records", fail)
    plates.download(plate_workspace)
    plates.normalize(plate_workspace)
    assert all(
        p.stat().st_mtime_ns == stamp
        for p, stamp in before.items()
        if "ledger.sqlite" not in p.name and p.suffix != ".lock"
    )
    monkeypatch.setattr(plates_normalize, "records", reader)
    Path(manifest["partitions"][0]["path"]).write_bytes(b"broken")
    plates.normalize(plate_workspace)
    assert load_manifest(plate_workspace, "plates")["rows"]["plate_codes"] == 1
    (plate_workspace.raw("plates") / "snapshot/wiki-XY.json").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Corrupt raw snapshot"):
        plates.normalize(plate_workspace)


def test_changed_source_pin_fails_instead_of_accepting_new_bytes(
    plate_workspace: Workspace,
) -> None:
    plates.download(plate_workspace)
    config = plates_config.DATA / "sources.json"
    sources = json.loads(config.read_text())
    sources["countries.csv"]["sha256"] = "0" * 64
    write_json(config, sources)
    with pytest.raises(ValueError, match="pins changed"):
        plates.download(plate_workspace)
