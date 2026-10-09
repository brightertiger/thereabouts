"""Plate tables in the writer's contract, built only from pinned evidence."""

import csv
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.engines.artifact_io import file_record
from pipeline.engines.artifacts import read_json
from pipeline.engines.plate_country import build, documents, evidence, formats, priors
from pipeline.runtime.jsonio import sha256_file, write_json
from pipeline.sources.shared.plates_schemas import PLATE_SCHEMAS
from tests.pipeline.sources.test_plate_country_sources import wiki

Row = dict[str, Any]
FIELDS = [
    "ISO3166-1-Alpha-2",
    "ISO3166-1-Alpha-3",
    "CLDR display name",
    "Region Name",
    "official_name_en",
    "UNTERM English Short",
]


def stored(root: Path, path: Path, metadata: Row) -> Row:
    """Move a file into the content-addressed raw store and describe it."""
    digest = sha256_file(path)
    target = root / "raw/plates/sha256" / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)
    return {
        "name": metadata["key"],
        "path": target.relative_to(root).as_posix(),
        "sha256": digest,
        "size": target.stat().st_size,
        "url": f"https://example.invalid/{metadata['key']}",
        "metadata": metadata,
    }


def code(**more: Any) -> Row:
    row: Row = {name: None for name in PLATE_SCHEMAS["plate_codes"].names}
    row |= {
        "source": "plates",
        "source_id": "code-1",
        "country_code": "XY",
        "code": "AB",
        "name_en": "Alpha",
        "unit_kind": "district",
        "series_status": "current",
        "subdivision_codes": '["XY-01"]',
        "source_url": "https://example.invalid/wiki-XY.json",
        "scope": "registration_unit",
        "series_id": "ordinary",
        "source_release": "test",
        "license": "CC-BY-SA-4.0",
        "provenance": "{}",
    }
    return row | more


def workspace(root: Path) -> Row:
    root.mkdir(parents=True)
    countries = root / "countries.csv"
    with countries.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, FIELDS)
        writer.writeheader()
        writer.writerow(
            dict(zip(FIELDS, ["XY", "XYZ", "Example", "Test", "", ""], strict=True))
        )
    page = wiki(root / "page.json", "<p>Example plates read AB-123.</p>")
    files = [
        stored(
            root,
            countries,
            {"key": "countries.csv", "kind": "countries", "license": "PDDL-1.0"},
        ),
        stored(
            root,
            Path(page["path"]),
            {
                "key": "wiki-XY.json",
                "kind": "wikipedia",
                "revision": 123,
                "license": "CC-BY-SA-4.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                "attribution": "Wikipedia contributors",
            },
        ),
    ]
    inventory = root / "raw/plates/inventory.json"
    write_json(
        inventory,
        {
            "pinned_at": "2026-10-01T00:00:00+00:00",
            "files": {item["name"]: item for item in files},
        },
    )
    part = root / "normalized/plates/plate_codes/h/part.parquet"
    part.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist([code()], schema=PLATE_SCHEMAS["plate_codes"]), part
    )
    return {
        "source": "plates",
        "inventory": file_record(root, inventory),
        "partitions": [{**file_record(root, part), "kind": "plate_codes", "rows": 1}],
    }


@pytest.fixture
def rules(monkeypatch: pytest.MonkeyPatch) -> Row:
    pinned = dict(
        series_id="ordinary",
        series_status="current",
        source="wiki-XY.json",
        pattern="(?P<code>[A-Z]{2})-[0-9]{3}",
        evidence_pattern="Example plates read",
        code_group="code",
    )
    unpinned = dict(pinned, country_code="QQ", source="wiki-QQ.json")
    config: Row = dict(
        formats=[unpinned],
        supplemental_formats=[],
        templates=[],
        state_tables=[
            dict(
                country_code="QQ",
                source="wiki-QQ.json",
                table=0,
                code_column=0,
                name_column=1,
            )
        ],
        prior_aliases={},
    )
    for module in (formats, evidence, priors):
        monkeypatch.setattr(module, "policy", lambda name: config[name])
    monkeypatch.setattr(formats, "base_policy", lambda name: {"XY": [pinned]})
    return config


def local(root: Path, manifest: Row) -> Row:
    return {
        **manifest,
        "partitions": [
            {**p, "path": str(root / p["path"])} for p in manifest["partitions"]
        ],
    }


def run(root: Path, manifest: Row, extra: list[Row] | None = None) -> Row:
    pins = documents.pool(root, manifest, extra or [], "plate_country")
    build.build(root, root / "out", local(root, manifest), pins, 2)
    return read_json(root / "out/manifest.json")


def table(root: Path, saved: Row, kind: str) -> list[Row]:
    (record,) = [t for t in saved["tables"] if t["kind"] == kind]
    return pq.read_table(root / record["path"]).to_pylist()


def test_writer_tables_from_pinned_evidence_only(tmp_path: Path, rules: Row) -> None:
    root = tmp_path / "ws"
    saved = run(root, workspace(root))
    assert sorted(t["kind"] for t in saved["tables"]) == [
        "plate_codes",
        "plate_formats",
        "plate_policy",
        "plate_priors",
    ]
    (rule,) = table(root, saved, "plate_formats")
    assert rule["country_code"] == "XY" and rule["code_group"] == "code"
    assert rule["relaxed_pattern"] != rule["pattern"]
    assert rule["scripts"] == ["Latin", "ASCII digits"]
    assert rule["specificity_bits"] > 0 and rule["fixed_national_marks"] == []
    assert rule["source"] == "plates" and rule["source_file"] == "wiki-XY.json"
    assert rule["license"] == "CC-BY-SA-4.0"
    assert json.loads(rule["provenance"])["revision"] == 123
    (row,) = table(root, saved, "plate_codes")
    assert row["subdivision_codes"] == ["XY-01"] and row["source"] == "plates"
    assert table(root, saved, "plate_priors") == []
    (policy,) = table(root, saved, "plate_policy")
    value = json.loads(policy["policy_json"])
    assert {48, 0x660} <= set(value["decimal_zeroes"])
    assert {
        "max_input_length",
        "code_separators",
        "levels",
        "script_patterns",
        "weights",
        "geography",
        "decimal_unicode_version",
    } <= set(value)
    coverage = read_json(root / "out/coverage.json")
    assert coverage["prior_available"] is False
    assert coverage["unpinned_sources"] == {"vehicle-stock.json": 1, "wiki-QQ.json": 2}
    assert "inputs_hash" not in json.dumps(saved)


def test_changed_evidence_bytes_fail_closed(tmp_path: Path, rules: Row) -> None:
    root = tmp_path / "ws"
    manifest = workspace(root)
    inventory = read_json(root / "raw/plates/inventory.json")
    page = root / inventory["files"]["wiki-XY.json"]["path"]
    page.write_text(page.read_text().replace("AB-123", "AB-124"))
    with pytest.raises(ValueError, match=r"Corrupt plate evidence: wiki-XY\.json"):
        run(root, manifest)


def test_conflicting_pins_fail_closed(tmp_path: Path, rules: Row) -> None:
    root = tmp_path / "ws"
    manifest = workspace(root)
    other = root / "other.json"
    other.write_text("{}")
    extra = [{**file_record(root, other), "name": "countries.csv", "upstream": {}}]
    with pytest.raises(ValueError, match=r"Conflicting plate evidence: countries\.csv"):
        documents.pool(root, manifest, extra, "plate_country")


def test_changed_inventory_fails_closed(tmp_path: Path, rules: Row) -> None:
    root = tmp_path / "ws"
    manifest = workspace(root)
    (root / "raw/plates/inventory.json").write_text("{}")
    with pytest.raises(ValueError, match="Corrupt plate evidence"):
        documents.pool(root, manifest, [], "plate_country")


def test_reference_resolver_without_priors_drops_the_prior_term(
    tmp_path: Path, rules: Row
) -> None:
    from pipeline.engines.plate_country.resolver import Resolver

    root = tmp_path / "ws"
    run(root, workspace(root))
    resolver = Resolver(read_json(root / "out/bundle.json"))
    (candidate,) = resolver.resolve("AB-123")["candidates"]
    (match,) = candidate["evidence"]
    assert match["score_components"]["log_vehicle_prior"] == 0
    assert match["prior"] is None
