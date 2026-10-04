"""Freeze IP boundary, family and malformed-input vectors."""

import ipaddress

from tests.client.conformance.pack_selection import selection
from tests.tools.build_forward_vectors import FIXTURES, write
from tests.tools.source_fixture import read_source
from thereabouts import Geocoder


def main() -> None:
    source = read_source(FIXTURES / "ip-source.json.gz")
    selected: set[tuple[str, int]] = set()
    requests = []
    for row in source["rows"]:
        key = (row["country_code"], row["ip_version"])
        if key in selected or row["country_code"] == "CA":
            continue
        selected.add(key)
        first, last = (
            int(ipaddress.ip_address(row["ip_start"])),
            int(ipaddress.ip_address(row["ip_end"])),
        )
        cls = ipaddress.IPv4Address if row["ip_version"] == 4 else ipaddress.IPv6Address
        for address in (first, (first + last) // 2, last):
            requests.append(
                {
                    "kind": "ip",
                    "values": [str(cls(address))],
                    "country": row["country_code"],
                }
            )
    requests += [
        {"kind": "ip", "values": [a]}
        for a in [
            "8.8.8.8",
            "2001:4860:4860::8888",
            "::1",
            "127.0.0.1",
            "::ffff:8.8.8.8",
            "255.255.255.255",
            "ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
            "",
            "01.2.3.4",
            "256.1.1.1",
            "1.2.3.4/24",
            "1.2.3.4:80",
            "fe80::1%en0",
            "::gg",
            "1.2.3",
            "1.2.3.4\0",
        ]
    ]
    for row in source["rows"]:
        if row["country_code"] == "CA":
            requests.extend(
                {"kind": "ip", "values": [row[k]], "country": "CA"}
                for k in ("ip_start", "ip_end")
            )
    with Geocoder(packs=selection(FIXTURES / "packs/ip-sample")) as geo:
        cases = [
            {
                "id": f"ip-{i:03}",
                "request": r,
                "result": geo.ip(r["values"][0]).to_dict(),
            }
            for i, r in enumerate(requests)
        ]
    write(FIXTURES / "ip-vectors.json", "packs/ip-sample", cases)
    print(f"Frozen {len(cases)} IP vectors")


if __name__ == "__main__":
    main()
