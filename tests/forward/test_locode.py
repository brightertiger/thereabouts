"""LOCODE vectors and independent published source associations."""

import json
from pathlib import Path

import pytest

from tests.conformance.forward_legacy import resolve
from tests.conformance.pack_selection import selection
from thereabouts import Geocoder
from tools.source_fixture import read_source

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_locode_vectors() -> None:
    bundle = json.loads((FIXTURES / "locode-vectors.json").read_text())
    with Geocoder(packs=selection(FIXTURES / bundle["pack"])) as geo:
        for case in bundle["cases"]:
            assert resolve(geo, case["request"]).to_dict() == case["result"], case["id"]


def test_independent_locode_sources() -> None:
    oracle = read_source(FIXTURES / "locode-source.json.gz")
    with Geocoder(packs=selection(FIXTURES / "packs/locode-sample")) as geo:
        for row in oracle["rows"]:
            result = geo.locode(row["locode"], evidence=True)
            assert (
                result.to_dict()
                == geo.locode(
                    row["location"], country=row["country_code"], evidence=True
                ).to_dict()
            )
            answers = result.candidates if result.status == "ambiguous" else (result,)
            matches = [
                a
                for a in answers
                if a.evidence
                and any(
                    dict(s).get("source_id") == row["source_id"]
                    for s in a.evidence.source_ids or ()
                )
            ]
            assert len(matches) == 1
            answer = matches[0]
            assert answer.kind == "trade_location" and answer.match == "exact"
            assert answer.evidence is not None
            assert answer.evidence.country_id == row["country_id"]
            assert answer.evidence.state_id == row["state_id"]
            assert answer.evidence.city_id == (
                oracle["place_to_city"].get(row["city_id"]) or row["city_id"]
            )
            assert row["name"] in [
                dict(s).get("name") for s in answer.evidence.source_ids or ()
            ]
            if row["latitude"] is None:
                assert answer.point is None
            else:
                assert answer.point is not None
                assert answer.point.lat == pytest.approx(
                    row["latitude"], abs=0.00000051
                )
                assert answer.point.lon == pytest.approx(
                    row["longitude"], abs=0.00000051
                )


def test_locode_columns() -> None:
    oracle = read_source(FIXTURES / "locode-source.json.gz")
    codes = [r["locode"] for r in oracle["rows"][:12]] + ["", "ZZZZZ", "BOM"]
    with Geocoder(packs=selection(FIXTURES / "packs/locode-sample")) as geo:
        columns = geo.locode_columns(codes)
        assert columns["status_categories"][columns["status"]].tolist() == [
            geo.locode(c).status for c in codes
        ]
