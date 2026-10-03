"""The enriched synthetic dataset exercises side-table export end to end."""

import json
from pathlib import Path

from thereabouts import Geocoder

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
