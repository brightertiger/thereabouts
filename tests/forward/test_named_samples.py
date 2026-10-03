"""Named examples must exist in both the independent extracts and the packs."""

import ipaddress
import json
from pathlib import Path

from thereabouts import Geocoder

FIXTURES = Path(__file__).parents[1] / "fixtures"


def test_google_ipv6_country_exception() -> None:
    address = "2001:4860:4860::8888"
    value = int(ipaddress.ip_address(address))
    rows = json.loads((FIXTURES / "ip-source.json").read_text())["rows"]
    matches = [
        r
        for r in rows
        if r["ip_version"] == 6
        and int(ipaddress.ip_address(r["ip_start"]))
        <= value
        <= int(ipaddress.ip_address(r["ip_end"]))
    ]
    assert len(matches) == 1 and matches[0]["country_code"] == "CA"
    with Geocoder(FIXTURES / "packs/ip-sample") as geo:
        result = geo.ip(address, evidence=True)
        assert result.status == "matched"
        assert result.country is not None and result.country.code == "CA"
        assert result.evidence is not None
        assert any(
            dict(s)["source_id"] == matches[0]["source_id"]
            for s in result.evidence.source_ids or ()
        )


def test_bombay_locode_and_published_mumbai_phone_prefix() -> None:
    rows = json.loads((FIXTURES / "locode-source.json").read_text())["rows"]
    assert any(r["locode"] == "INBOM" for r in rows)
    with Geocoder(FIXTURES / "packs/locode-sample") as geo:
        result = geo.locode("INBOM")
        assert result.status == "matched"
        assert result.country is not None and result.country.code == "IN"
        assert result == geo.locode("BOM", country="IN")
    rows = json.loads((FIXTURES / "phone-source.json").read_text())["rows"]
    prefixes = {r["prefix"] for r in rows if (r["prefix"] or "").startswith("9122")}
    assert prefixes == {"91222", "91223", "91224", "91225", "91226", "91227"}
    with Geocoder(FIXTURES / "packs/phone-sample") as geo:
        result = geo.phone("+91 22 2345 6789", evidence=True)
        assert result.status == "matched"
        assert result.country is not None and result.country.code == "IN"
        assert result.evidence is not None
        sources = [dict(s) for s in result.evidence.source_ids or ()]
        assert all(s["code"] == "91222" for s in sources)
        assert (
            result.city is None
        )  # Published description is not a canonical city link.
