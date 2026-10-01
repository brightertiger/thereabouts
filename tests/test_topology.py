from pathlib import Path

from shapely.geometry import box

from build_data.pack import write_pack
from pyofflinegeocoder import Geocoder


def test_shared_boundary_returns_all_candidates_in_stable_order(
    synthetic: Geocoder,
) -> None:
    result = synthetic.reverse(1, 5)
    assert result.admin1.status == "ambiguous"
    assert result.admin1.value is None
    assert [a.id for a in result.admin1.candidates] == ["test:L", "test:R"]
    assert synthetic.reverse(1, 5 + 0.5e-9).admin1.status == "ambiguous"
    assert synthetic.reverse(1, 5 + 2e-9).admin1.status == "matched"


def test_overlapping_claims_are_ambiguous(synthetic: Geocoder) -> None:
    result = synthetic.reverse(1, 9.5)
    assert result.country.status == "ambiguous"
    assert result.country.value is None
    assert [a.id for a in result.country.candidates] == ["test:A", "test:C"]


def test_enclave_and_tiny_multipart_island(synthetic: Geocoder) -> None:
    enclave = synthetic.reverse(3.5, 3.5)
    assert enclave.country.value is not None and enclave.country.value.id == "test:B"
    island = synthetic.reverse(19.005, 19.005)
    assert island.country.value is not None and island.country.value.id == "test:A"
    assert island.land_status == "inside_mask"


def test_missing_subdivision_and_explicit_nonapplicability_differ(
    synthetic: Geocoder,
) -> None:
    assert synthetic.reverse(1, 13).admin1.status == "not_applicable"
    missing = synthetic.reverse(1, 16)
    assert missing.admin1.status == "no_coverage"
    assert missing.country.value is not None and missing.country.value.code is None
    gap = synthetic.reverse(17, 17)
    assert gap.land_status == "inside_mask"
    assert gap.country.status == gap.admin1.status == "no_coverage"


def test_coincident_and_equidistant_places_use_smallest_geonames_id(
    synthetic: Geocoder,
) -> None:
    for lon in (4, 5):
        result = synthetic.reverse(1, lon, max_place_distance_km=None)
        assert (
            result.nearest_place is not None and result.nearest_place.geoname_id == 10
        )
        assert result.nearest_place.source_country_code == "ZZ"
        assert result.country.value is not None and result.country.value.code == "AA"


def test_land_without_settlements_has_no_place_coverage(tmp_path: Path) -> None:
    path = tmp_path / "empty"
    write_pack(path, [], [], [box(0, 0, 1, 1)], [], None, [], snapshot_id="empty-test")
    with Geocoder(path) as geocoder:
        geocoder.verify()
        result = geocoder.reverse(0.5, 0.5)
        assert result.place_status == "no_coverage" and result.nearest_place is None
