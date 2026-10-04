"""IP boundaries are asserted independently against committed source ranges."""

import ipaddress
import json
from pathlib import Path

import pytest

from tests.client.conformance.pack_selection import selection
from tests.tools.source_fixture import read_source
from thereabouts import Geocoder

FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_ip_vectors() -> None:
    bundle = json.loads((FIXTURES / "ip-vectors.json").read_text())
    with Geocoder(packs=selection(FIXTURES / bundle["pack"])) as geo:
        for case in bundle["cases"]:
            assert geo.ip(case["request"]["values"][0]).to_dict() == case["result"], (
                case["id"]
            )


def test_independent_interval_boundaries() -> None:
    source = read_source(FIXTURES / "ip-source.json.gz")
    rows = source["rows"]
    ranges = [
        (
            r["ip_version"],
            int(ipaddress.ip_address(r["ip_start"])),
            int(ipaddress.ip_address(r["ip_end"])),
            r,
        )
        for r in rows
    ]
    with Geocoder(packs=selection(FIXTURES / "packs/ip-sample")) as geo:
        for version, first, last, row in ranges:
            cls = ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address
            for address in (first, (first + last) // 2, last):
                answer = geo.ip(str(cls(address)), evidence=True)
                assert answer.kind == "ip_range" and answer.status == "matched"
                assert answer.evidence is not None
                observed = [dict(s) for s in answer.evidence.source_ids or ()]
                assert {(s["source"], s["source_id"]) for s in observed} == {
                    (row["source"], row["source_id"])
                }
                assert answer.evidence.country_id == row["country_id"]
                assert answer.evidence.city_id == (
                    source["place_to_city"].get(row["city_id"]) or row["city_id"]
                )
                details = json.loads(observed[0]["details"])
                assert (
                    details["region"] == row["region"]
                    and details["city"] == row["city"]
                )
                if row["latitude"] is not None:
                    assert answer.point is not None
                    assert answer.point.lat == pytest.approx(
                        row["latitude"], abs=0.00000051
                    )
                    assert answer.point.lon == pytest.approx(
                        row["longitude"], abs=0.00000051
                    )
            # The successor belongs to another published range or misses.
            if last < (1 << (32 if version == 4 else 128)) - 1:
                expected = next(
                    (r for v, a, b, r in ranges if v == version and a <= last + 1 <= b),
                    None,
                )
                answer = geo.ip(str(cls(last + 1)), evidence=True)
                assert answer.status == ("matched" if expected else "not_found")
                if expected:
                    assert answer.evidence is not None
                    assert (
                        dict((answer.evidence.source_ids or ())[0])["source_id"]
                        == expected["source_id"]
                    )


def test_ip_columns() -> None:
    source = read_source(FIXTURES / "ip-source.json.gz")
    values = [r["ip_start"] for r in source["rows"][:10]] + ["invalid", "::1"]
    with Geocoder(packs=selection(FIXTURES / "packs/ip-sample")) as geo:
        columns = geo.ip_columns(addresses=values)
        assert columns["status_categories"][columns["status"]].tolist() == [
            geo.ip(v).status for v in values
        ]
