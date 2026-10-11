"""Pipeline-shaped names and plate tables go through assemble() and the real writer."""

import json
from pathlib import Path

from pipeline.release import client
from tests.skill.dataset import PARIS
from thereabouts import Geocoder

from .synthetic import dataset as synthetic_dataset


def test_names_and_plates_through_assemble_and_writer(tmp_path: Path) -> None:
    dataset, _ = synthetic_dataset(tmp_path)
    manifest = json.loads((dataset / "manifest.json").read_text())
    assert manifest["statistics"]["names"]["rows"] == 1
    assert manifest["statistics"]["plate_policy"]["rows"] == 1
    notices = (dataset / "DATA_LICENSES.md").read_text()
    assert "`CC-BY-SA-4.0`" in notices and "**Share-alike content.**" in notices
    assert "OWNER DECISION" not in notices
    packs = tmp_path / "packs"
    writer = client.binding()
    for family in ("core", "plates"):
        client.write(dataset, family, packs / family, "2026.10", writer)
    with Geocoder(packs={"core": packs / "core", "plates": packs / "plates"}) as geo:
        found = geo.geocode("Lutetia")
        assert found.city is not None and found.city.id == PARIS
        assert found.match == "alternate_name"
        assert geo.geocode("Paris").match == "exact"
        plate = geo.plate("AB-123-CD 75", evidence=True)
        assert plate.country is not None and plate.country.code == "FR"
        assert plate.rank_basis == "plate_evidence_without_vehicle_prior"
        hinted = geo.plate("AB-123-CD 75", country="FR")
        assert hinted.country is not None and hinted.country.code == "FR"
