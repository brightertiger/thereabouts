"""Every pinned licence remains visible in the shipped notices."""

from dataclasses import replace

import pytest

from pipeline.config import load
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
