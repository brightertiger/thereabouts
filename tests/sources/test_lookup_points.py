"""Synthetic coordinate, code, prefix, schema and range edge cases."""

import json

import h3
import pyarrow as pa
import pytest

from pipeline.config.schema import H3
from pipeline.config.sources import SourceLimits
from pipeline.sources.airports import airport
from pipeline.sources.codes import country, subdivision
from pipeline.sources.dbip import ip_range
from pipeline.sources.phone import prefix
from pipeline.sources.postal import postal
from pipeline.sources.shared.iana import coordinates
from pipeline.sources.shared.lookup_rows import Reject, decorate, point
from pipeline.sources.shared.lookup_schemas import LOOKUP_SCHEMAS
from pipeline.sources.shared.schemas import validate_table
from pipeline.sources.unlocode import trade


@pytest.mark.parametrize(
    "lat,lon", [(12.9716, 77.5946), (40.7128, -74.006), (90, 180), (-90, -180), (0, 0)]
)
@pytest.mark.parametrize("resolution", [7, 8])
def test_point_keys_are_canonical_and_contain_the_coordinate(
    lat: float, lon: float, resolution: int
) -> None:
    row = point(lat, lon, grid=H3(cell_resolution=resolution))
    assert row["h3"] == h3.latlng_to_cell(lat, lon, resolution)
    assert h3.str_to_int(row["h3"]) == row["h3_uint64"]
    assert row["h3_resolution"] == resolution


def test_invalid_coordinate_keeps_trade_record_and_raw_evidence() -> None:
    raw = {
        "Country": "IN",
        "Location": "BLR",
        "Coordinates": "1260N 07730E",
        "Function": "1234567B",
    }
    row = trade(raw, grid=H3())
    assert row["h3"] is None and row["function"] == "1234567B"
    result = decorate(
        row,
        "unlocode",
        "id",
        dict(
            url="https://example.invalid",
            license="PDDL",
            license_url="https://example.invalid/license",
            attribution="UNECE",
            retrieved_at="today",
        ),
        "release",
        raw,
    )
    assert result["locode"] == "INBLR"
    assert json.loads(result["provenance"])["coordinate_error"]
    assert json.loads(result["provenance"])["raw"] == raw


def test_postal_variants_and_closed_airports_are_not_filtered() -> None:
    raw = [
        "IN",
        "560001",
        "Bengaluru",
        "Karnataka",
        "KA",
        "Bengaluru",
        "01",
        "",
        "",
        "12.9767",
        "77.5786",
        "6",
    ]
    row = postal(raw, "allCountries.zip", grid=H3())
    assert row["accuracy"] == "6" and row["postal_code"] == "560001"
    assert row["admin2_name"] == "Bengaluru"
    with pytest.raises(Reject):
        postal(raw[:-1], "bad", grid=H3())
    result = airport(
        {
            "type": "closed",
            "iso_country": "US",
            "latitude_deg": "1",
            "longitude_deg": "2",
        },
        grid=H3(),
    )
    assert result["type"] == "closed" and result["h3"]


@pytest.mark.parametrize(
    "start,end",
    [
        ("8.8.8.0", "8.8.8.255"),
        ("2001:4860::", "2001:4860:ffff:ffff:ffff:ffff:ffff:ffff"),
    ],
)
def test_ranges_preserve_both_address_families(start: str, end: str) -> None:
    row = ip_range(
        [start, end, "NA", "US", "California", "Mountain View", "37.4", "-122.1"],
        grid=H3(),
    )
    assert row["ip_start"] == start and row["ip_end"] == end
    assert len(row["ip_start_packed"]) == 16
    assert row["ip_start_packed"] <= row["ip_end_packed"]
    with pytest.raises(Reject):
        ip_range([end, start, "NA", "US", "", "", "0", "0"], grid=H3())


def test_code_systems_zero_padding_and_shared_phone_codes() -> None:
    row = country(
        {"ISO3166-1-Alpha-2": "IN", "ISO3166-1-numeric": "356", "Region Code": "142"},
        {},
    )
    assert row["numeric"] == "356" and row["region_code"] == "142"
    assert country({"ISO3166-1-numeric": "4"}, {})["numeric"] == "004"
    row = subdivision({"fields": ["FR.84", "Auvergne", "Auvergne", "11071625"]})
    assert row["code_system"] == "GeoNames-admin1" and row["country_code"] == "FR"
    assert row["geoname_id"] == "11071625" and "parent_code" not in row
    row = prefix(
        {"fields": ["1201", "New Jersey"]},
        "resources/geocoding/en/1.txt",
        {"1": ["US", "CA"], "91": ["IN"]},
    )
    assert row["country_codes"] == ["US", "CA"] and row["language"] == "en"
    assert coordinates("+404251-0740023", grid=H3())["h3"] == h3.latlng_to_cell(
        40 + 42 / 60 + 51 / 3600, -(74 + 23 / 3600), 8
    )


def test_lookup_schema_rejects_wrong_cell_and_blank_string(
    limits: SourceLimits,
) -> None:
    row = decorate(
        dict(country_code="IN", postal_code="560001", **point(12.97, 77.59, grid=H3())),
        "postal",
        "id",
        dict(
            url="https://example.invalid",
            license="CC-BY",
            license_url="https://example.invalid/license",
            attribution="GeoNames",
            retrieved_at="today",
        ),
        "release",
        {},
    )
    table = pa.Table.from_pylist([row], schema=LOOKUP_SCHEMAS["postal_codes"])
    validate_table(table, "postal_codes", "postal", limits, grid=H3())
    row["h3_uint64"] += 1
    with pytest.raises(ValueError, match="H3"):
        validate_table(
            pa.Table.from_pylist([row], schema=table.schema),
            "postal_codes",
            "postal",
            limits,
            grid=H3(),
        )
    row["h3_uint64"] -= 1
    row["postal_code"] = "\u00a0"
    with pytest.raises(ValueError, match="missing strings"):
        validate_table(
            pa.Table.from_pylist([row], schema=table.schema),
            "postal_codes",
            "postal",
            limits,
            grid=H3(),
        )


@pytest.fixture
def limits() -> SourceLimits:
    return SourceLimits()
