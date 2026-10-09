"""Every pinned licence remains visible in the shipped notices."""

from pipeline.config import load
from pipeline.release.licensing import rows
from pipeline.release.metadata import licence_text, licences


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
