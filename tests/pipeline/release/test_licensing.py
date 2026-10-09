"""Every pinned licence remains visible in the shipped notices."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.config import load, policies
from pipeline.pins.lock import read_lock
from pipeline.release import metadata
from pipeline.release.licensing import rows
from pipeline.release.metadata import licence_text, licences
from pipeline.runtime.fingerprints import REPOSITORY


def test_per_file_licences_and_attributions_are_not_hidden() -> None:
    sources = licences(load(), {"codes", "timezones"})
    text = licence_text(sources, {"PDDL-1.0 AND CC-BY-4.0"})
    assert "`PDDL-1.0 AND CC-BY-4.0`" in text
    expected = {
        file["metadata"]["license"]
        for name in ("codes", "timezones")
        for file in sources[name]["pin"]["files"]
    }
    assert expected == {
        "CC-BY-4.0",
        "PDDL-1.0",
        "ODbL-1.0",
        "Public-Domain",
    }
    assert all(f"| {licence} |" in text for licence in expected)
    assert "LGPL" not in text and "pycountry" not in text
    assert "`admin1CodesASCII.txt`" in text
    assert "manifest.json.sources" in text and "pins.lock" not in text
    grouped = rows(sources)
    codes = [row for row in grouped if row["source"] == "codes"]
    assert {row["license"] for row in codes} == {"CC-BY-4.0", "PDDL-1.0"}
    assert len(codes) == 3
    for file in sources["geoboundaries"]["pin"]["files"]:
        assert file["metadata"]["metadata"]["boundaryLicense"] in text


def test_output_ceiling_uses_profile_and_workspace_overrides() -> None:
    for profile in (None, "vm"):
        config = load(
            profile=profile, overrides=["resources.max_workspace=90000000000"]
        )
        assert config.release.dataset.max_output_bytes == 90_000_000_000
    assert load(profile="laptop").release.dataset.max_output_bytes == 3_000_000_000
    assert (
        load(
            profile="vm", overrides=["release.dataset.max_output_bytes=1234"]
        ).release.dataset.max_output_bytes
        == 1234
    )


def test_plate_licences_are_listed_and_cc_by_sa_awaits_the_owner() -> None:
    sources = licences(load(), {"plates"})
    text = licence_text(sources, {"CC-BY-SA-4.0", "CC0-1.0"})
    for licence in (
        "CC-BY-SA-4.0",
        "CC0-1.0",
        "OGL-UK-3.0",
        "PDDL-1.0",
        "LicenseRef-PDL-1.0",
        "LicenseRef-PD-Poland-Article4",
        "LicenseRef-PD-Thailand-Section7",
    ):
        assert f"| plates | {licence} |" in text
    assert text.count("OWNER DECISION") == 1
    assert "plates" in text.split("OWNER DECISION", 1)[1]
    plain = licence_text(licences(load(), {"codes"}), {"CC-BY-4.0"})
    assert "OWNER DECISION" not in plain


EXCLUDED = (
    "ShareAlike",
    "CC BY 3.0 IGO",
    "Pixabay",
    "Other - Humanitarian",
    "Etalab",
    "Open Government Canada",
    "swisstopo",
)


def boundaries(sources: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        file["metadata"]["metadata"]
        for file in sources["geoboundaries"]["pin"]["files"]
    ]


def test_only_geoboundaries_layers_the_build_uses_are_listed() -> None:
    config = load()
    pinned = (REPOSITORY / "pins.lock").read_text()
    assert all(name in pinned for name in EXCLUDED)
    compatible = set(policies.reconcile()["compatible_gb_licenses"])
    sources = licences(config, set())
    layers = boundaries(sources)
    assert layers and all(layer["boundaryType"] in {"ADM0", "ADM1"} for layer in layers)
    assert all(
        " ".join(layer["boundaryLicense"].split()) in compatible for layer in layers
    )
    text = licence_text(sources, set())
    for name in EXCLUDED:
        assert name not in text, name
    # State layers only for countries whose states came from geoBoundaries.
    chosen = sorted(x["boundaryISO"] for x in layers if x["boundaryType"] == "ADM1")[0]
    narrowed = boundaries(licences(config, set(), {chosen}))
    assert {x["boundaryISO"] for x in narrowed if x["boundaryType"] == "ADM1"} == {
        chosen
    }
    assert sum(x["boundaryType"] == "ADM0" for x in narrowed) == sum(
        x["boundaryType"] == "ADM0" for x in layers
    )
    assert not [
        x
        for x in boundaries(licences(config, set(), set()))
        if x["boundaryType"] == "ADM1"
    ]


def test_cc_by_sources_are_marked_modified() -> None:
    text = licence_text(licences(load(), {"codes"}), {"CC-BY-4.0"})
    statement = text.split("**Modifications.**", 1)[1].split("\n\n", 1)[0]
    for name in ("geonames", "geoboundaries", "codes"):
        assert name in statement
    assert "modified" in statement
    plain = licence_text(licences(load(), {"timezones"}), set())
    assert "**Modifications.**" in plain  # geographic inputs are always CC BY


def test_apache_licence_text_ships_once_with_libphonenumber() -> None:
    marker = "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION"
    text = licence_text(licences(load(), {"phone"}), {"Apache-2.0"})
    assert text.count(marker) == 1
    assert "phone" in text.split(marker, 1)[0].rsplit("## Apache License", 1)[1]
    assert marker not in licence_text(licences(load(), {"codes"}), set())


def test_public_sources_carry_no_custody_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load(overrides=["storage.gcs_raw=gs://private-bucket/raw"])
    pins = read_lock(REPOSITORY / "pins.lock")
    pin = pins["timezones"]
    pin.metadata["mirror_base"] = "gs://private-bucket/raw"
    pin.metadata["mirror_evidence"] = {"bucket": "private-bucket"}
    pin.files[0].metadata["mirror"] = "gs://private-bucket/raw/sha256/x"
    monkeypatch.setattr(metadata, "read_lock", lambda path: pins)
    encoded = json.dumps(licences(config, {"timezones"}))
    assert "mirror" not in encoded and "private-bucket" not in encoded


def test_state_layers_follow_the_dataset_states(tmp_path: Path) -> None:
    places = pa.table(
        {
            "place_id": ["state:geoboundaries:x", "state:overture:y", "city:a"],
            "country_code": ["CA", "US", "CA"],
        }
    )
    pq.write_table(places, tmp_path / "places.parquet")
    countries = pa.table({"country_code": ["CA", "US"], "alpha3": ["CAN", "USA"]})
    pq.write_table(countries, tmp_path / "countries.parquet")
    tables = [
        {"kind": "places", "path": "places.parquet"},
        {"kind": "countries", "path": "countries.parquet"},
    ]
    assert metadata.boundary_states(tmp_path, tables) == {"CAN"}
    pq.write_table(countries.slice(1), tmp_path / "countries.parquet")
    with pytest.raises(ValueError, match="lack alpha-3"):
        metadata.boundary_states(tmp_path, tables)


def test_evaluation_files_are_pinned_but_never_listed_as_shipped() -> None:
    def pinned(name: str, **metadata: str) -> dict[str, object]:
        return {"name": name, "metadata": {"license": "CC-BY-SA-4.0"} | metadata}

    sources = {
        "plate_country": {
            "id": "per-source",
            "attribution": "Wikipedia and Wikimedia Commons contributors",
            "pin": {
                "files": [
                    pinned("vehicle-stock.json", attribution="en.wikipedia.org"),
                    pinned("eval-commons-DE.json", purpose="evaluation"),
                    pinned(
                        "eval-image-1.jpg", purpose="evaluation", license="CC-BY-2.0"
                    ),
                ]
            },
        }
    }
    (row,) = rows(sources)
    assert row["files"] == ["vehicle-stock.json"]
    text = licence_text(sources, {"CC-BY-SA-4.0"})
    assert "eval-" not in text and "CC-BY-2.0" not in text
    assert "plate_country" in text.split("OWNER DECISION", 1)[1]


def test_shipped_source_records_leave_out_evaluation_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = read_lock(REPOSITORY / "pins.lock")
    plates = lock["plates"]
    extra = replace(plates.files[0], name="eval-image-1.jpg")
    extra.metadata = {**extra.metadata, "purpose": "evaluation"}
    lock["plates"] = replace(plates, files=[*plates.files, extra])
    monkeypatch.setattr(metadata, "read_lock", lambda _: lock)
    names = [f["name"] for f in licences(load(), {"plates"})["plates"]["pin"]["files"]]
    assert "eval-image-1.jpg" not in names and len(names) == len(plates.files)
