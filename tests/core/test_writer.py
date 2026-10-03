"""The enriched synthetic dataset exercises side-table export end to end."""

import json
from pathlib import Path

from thereabouts import Geocoder, _core

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_writer_preserves_overlaps_without_ambiguous_reverse() -> None:
    vectors = json.loads((FIXTURES / "conformance.json").read_text())["cases"]
    with Geocoder(FIXTURES / "packs/core-synthetic") as geo:
        matched = geo.from_h3(vectors[0]["request"]["values"][0], evidence=True)
        assert matched.status == "matched"
        assert matched.country is not None and matched.country.code3 == "AAA"
        assert matched.timezone == "Fixture/One"
        unassigned = geo.from_h3(vectors[7]["request"]["values"][0], evidence=True)
        assert unassigned.status == "not_found" and unassigned.timezone is None
        assert unassigned.evidence is not None
        assert unassigned.evidence.timezones == ("Fixture/One", "Fixture/Two")
        assert unassigned.candidates == ()


def test_writer_staging_location_does_not_change_identity(tmp_path: Path) -> None:
    original = json.loads((FIXTURES / "packs/core-synthetic/manifest.json").read_text())
    options = original["inputs"]["options"] | {
        "staging_directory": str(tmp_path / "scratch"),
        "sqlite_directory": str(tmp_path / "sqlite"),
    }
    result = _core.write_pack(
        str(FIXTURES / "datasets/core-synthetic/golden"),
        "core",
        str(tmp_path / "pack"),
        options,
    )
    assert result == original
    assert "staging_directory" not in result["inputs"]["options"]
    assert list((tmp_path / "scratch").iterdir()) == []
    assert list((tmp_path / "sqlite").iterdir()) == []
    assert "sqlite_directory" not in result["inputs"]["options"]
    assert (tmp_path / "pack/manifest.json").is_file()


def test_source_extract_generator_retains_the_matched_place_ids(tmp_path: Path) -> None:
    from tools.sample_evidence import extract

    cases = json.loads((FIXTURES / "core-synthetic-vectors.json").read_text())["cases"]
    vectors = tmp_path / "vectors.json"
    vectors.write_text(json.dumps({"cases": [cases[0], cases[7]]}))
    output = tmp_path / "extract.json"
    extract(FIXTURES / "datasets/core-synthetic/golden", vectors, output, {})
    result = json.loads(output.read_text())
    assert set(result["places"]) == {
        "country:AA",
        "state:synthetic:A",
        "city:synthetic:A",
    }
    assert len(result["queries"]) == 2
