"""Release settings that the writer, the acceptance gate and publication rely on."""

import pytest

from pipeline.config import load
from pipeline.config.release import validate


def test_cell_groups_must_use_resolution_one() -> None:
    settings = load().release
    for resolution in (0, 2, 3):
        settings.dataset.cell_group_resolution = resolution
        # The writer reads only group=<r1> partitions.
        with pytest.raises(ValueError, match="resolution 1"):
            validate(settings, 3)
    settings.dataset.cell_group_resolution = 1
    validate(settings, 3)


def test_acceptance_defaults_follow_the_world_test() -> None:
    acceptance = load().release.acceptance
    assert acceptance.open_files == 256
    assert (acceptance.land_cells, acceptance.ocean_points) == (10000, 1000)
    assert (acceptance.names, acceptance.forward_rows) == (1000, 500)
    assert set(acceptance.minimum) == {
        "reverse",
        "ocean",
        "names",
        "alternate_names",
        "postal",
        "airports_iata",
        "airports_icao",
        "locode",
        "ip_v4",
        "ip_v6",
        "phone",
        "plates",
        "vectors",
    }
    assert all(value == 1.0 for value in acceptance.minimum.values())


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ("release.acceptance.minimum.reverse=1.5", "between 0 and 1"),
        ("release.acceptance.minimum.unknown=1.0", "Unknown acceptance check"),
        ("release.acceptance.open_files=16", "at least 64"),
        ("release.acceptance.land_cells=-1", "non-negative"),
    ],
)
def test_acceptance_settings_are_validated(override: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load(overrides=[override])


def test_publication_is_public_unless_declared_private() -> None:
    config = load()
    assert config.release.publish.private is False
    assert load(overrides=["release.publish.private=true"]).release.publish.private


def test_closure_aliases_only_exceptional_reservations_by_default() -> None:
    rules = load().release.dataset.closure
    # Anything not listed refuses the release, so a new code never passes silently.
    assert rules.unknown_places == "fail"
    assert rules.place_aliases == {
        "country": {"AC": "SH", "TA": "SH", "DG": "IO", "EA": "ES", "IC": "ES"}
    }
    assert rules.excluded_places == {}


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ("release.dataset.closure.unknown_places=drop", "fail or exclude"),
        ("release.dataset.closure.place_aliases.country.ZZ=ZZ", "to itself"),
        ("release.dataset.closure.place_aliases.country.ZZ=AC", "chain"),
        ("release.dataset.closure.place_aliases.country.Zz=SH", "two-letter"),
        ("release.dataset.closure.place_aliases.Country.ZZ=SH", "place kind"),
        ("release.dataset.closure.place_aliases.state.x=''", "empty"),
        ("release.dataset.closure.excluded_places.country=[AC]", "both"),
        ("release.dataset.closure.excluded_places.country=[ZZ,ZZ]", "twice"),
    ],
)
def test_closure_rules_are_validated(override: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load(overrides=[override])


def test_closure_rules_accept_other_place_kinds() -> None:
    rules = load(
        overrides=[
            "release.dataset.closure.unknown_places=exclude",
            "release.dataset.closure.place_aliases.state.overture:old=overture:new",
            "release.dataset.closure.excluded_places.city=[geonames:1]",
        ]
    ).release.dataset.closure
    assert rules.place_aliases["state"] == {"overture:old": "overture:new"}
    assert rules.excluded_places["city"] == ["geonames:1"]
