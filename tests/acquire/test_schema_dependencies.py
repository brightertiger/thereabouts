"""Separate plate contracts must not invalidate unrelated acquired sources."""

import importlib

import pytest

from build_data.acquire import schemas
from build_data.acquire.io import fingerprint
from build_data.acquire.plates_config import configuration as plate_configuration
from build_data.acquire.plates_schemas import PLATE_KINDS

MODULES = (
    "geonames_settings",
    "geoboundaries_settings",
    "overture_settings",
    "osm_land_settings",
    "lookup_normalize",
    "lookup_timezones",
)


@pytest.mark.parametrize("module", MODULES)
def test_plate_schema_changes_are_isolated(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration = importlib.import_module(
        f"build_data.acquire.{module}"
    ).configuration
    before = fingerprint(configuration())
    plate_before = fingerprint(plate_configuration())
    assert not set(PLATE_KINDS).intersection(configuration()["schemas"])
    monkeypatch.setitem(schemas.SCHEMA_HASHES, "plate_codes", "changed-schema")
    assert fingerprint(configuration()) == before
    assert fingerprint(plate_configuration()) != plate_before


@pytest.mark.parametrize("module", MODULES)
def test_existing_schema_changes_still_invalidate(
    module: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    configuration = importlib.import_module(
        f"build_data.acquire.{module}"
    ).configuration
    before = fingerprint(configuration())
    if module.startswith("lookup_"):
        monkeypatch.setitem(schemas.SCHEMA_HASHES, "postal_codes", "changed-schema")
    else:
        monkeypatch.setitem(schemas.CORE_SCHEMA_HASHES, "areas", "changed-schema")
    assert fingerprint(configuration()) != before


@pytest.mark.parametrize("module", MODULES[:4])
def test_geographic_source_contracts_exclude_independent_lookups(module: str) -> None:
    configuration = importlib.import_module(
        f"build_data.acquire.{module}"
    ).configuration
    assert configuration()["schemas"] == {
        kind: digest
        for kind, digest in schemas.SCHEMA_HASHES.items()
        if kind in ("areas", "places", "names")
    }
