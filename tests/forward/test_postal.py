"""Postal semantics, legacy mappings, independent source anchors and column batches."""

import json
from pathlib import Path

import numpy as np
import pytest

from tests.conformance.forward_legacy import check, resolve
from tests.conformance.pack_selection import selection
from thereabouts import ClosedGeocoderError, Geocoder, IncompatibleDataError
from tools.source_fixture import read_source

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.mark.parametrize(
    "name", ["postal-vectors.json", "postal-synthetic-vectors.json"]
)
def test_shared_vectors(name: str) -> None:
    bundle = json.loads((FIXTURES / name).read_text())
    with Geocoder(packs=selection(FIXTURES / bundle["pack"])) as geo:
        for case in bundle["cases"]:
            assert resolve(geo, case["request"]).to_dict() == case["result"], case["id"]


def test_original_legacy_expectations() -> None:
    assert check() == {"matched": 4, "ambiguous": 1, "not_found": 1, "invalid_input": 2}


def test_independent_postal_source_rows() -> None:
    oracle = read_source(FIXTURES / "postal-source.json.gz")
    rows = oracle["rows"]
    indexed = {(r["source"], r["source_id"]): r for r in rows}
    with Geocoder(packs=selection(FIXTURES / "packs/postal-sample")) as geo:
        for row in rows:
            result = geo.postal(
                row["postal_code"], country=row["country_code"], evidence=True
            )
            answers = result.candidates if result.status == "ambiguous" else (result,)
            matches = [
                answer
                for answer in answers
                if answer.evidence is not None
                and any(
                    dict(source).get("source_id") == row["source_id"]
                    for source in answer.evidence.source_ids or ()
                )
            ]
            assert len(matches) == 1
            answer = matches[0]
            assert answer.evidence is not None
            assert answer.evidence.country_id == row["country_id"]
            assert answer.evidence.state_id == row["state_id"]
            assert answer.evidence.city_id == (
                oracle["place_to_city"].get(row["city_id"]) or row["city_id"]
            )
            # A grouped postal locality uses its first source point, while all
            # contributing source identities and names remain in evidence.
            first = dict((answer.evidence.source_ids or ())[0])
            anchor = indexed[(first["source"], first["source_id"])]
            if anchor["latitude"] is None:
                assert answer.point is None
            else:
                assert answer.point is not None
                assert answer.point.lat == pytest.approx(
                    anchor["latitude"], abs=0.00000051
                )
                assert answer.point.lon == pytest.approx(
                    anchor["longitude"], abs=0.00000051
                )
            names = [dict(s).get("name") for s in answer.evidence.source_ids or ()]
            assert row["place_name"] in names


def test_columns_preserve_ambiguous_candidates_and_close() -> None:
    geo = Geocoder(packs=selection(FIXTURES / "packs/postal-synthetic"))
    columns = geo.postal_columns(["00100", "AMB", "missing"], country="AA")
    status = columns["status_categories"][columns["status"]].tolist()
    assert status == ["matched", "ambiguous", "not_found"]
    assert columns["candidate_offsets"].tolist() == [0, 0, 2, 2]
    assert columns["candidate_status_categories"][
        columns["candidate_status"]
    ].tolist() == ["matched", "matched"]
    assert columns["country_code"].dtype == np.int32
    geo.close()
    with pytest.raises(ClosedGeocoderError):
        geo.postal("00100", country="AA")


def test_explicit_family_selection_rejects_mixed_datasets() -> None:
    with pytest.raises(IncompatibleDataError, match="versions"):
        Geocoder(
            packs={
                "core": FIXTURES / "packs/core-sample",
                "postal": FIXTURES / "packs/postal-synthetic",
            }
        )


def test_postal_only_installation_does_not_require_core(tmp_path: Path) -> None:
    import shutil

    from thereabouts.store_files import sha256

    source = FIXTURES / "packs/postal-synthetic"
    digest = sha256(source / "manifest.json")
    path = tmp_path / f"packs/postal/v-synthetic/{digest}"
    shutil.copytree(source, path)
    (tmp_path / "packs/postal/current.json").write_text(
        json.dumps(
            {
                "path": str(path.relative_to(tmp_path)),
                "manifest_sha256": digest,
            }
        )
    )
    with Geocoder(data_dir=tmp_path) as geo:
        assert geo.postal("00100", country="AA").status == "matched"
