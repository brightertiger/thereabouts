"""Freeze plate vectors for ambiguity, scoped geography and conservative fallback."""

from typing import Any

from tests.client.conformance.pack_selection import selection
from tests.tools.build_forward_vectors import FIXTURES, write
from thereabouts import Geocoder


def main() -> None:
    examples = [
        ("1-ABC-123", "BE"),
        ("2-ABC-456", "BE"),
        ("12-ABC-3", "NL"),
        ("AB-12-CD", "NL"),
        ("AB 1234", "LU"),
        ("AB-123-CD", "FR"),
        ("34 ABC 1234", "TR"),
        ("06 AB 123", "TR"),
        ("MH 12 AB 1234", "IN"),
        ("MH 99 AB 1234", "IN"),
        ("22 BH 1234 AA", "IN"),
        ("ABC 123", "US"),
        ("1A 12345", "US"),
        ("unknown", "FR"),
        ("", "IN"),
    ]
    requests: list[dict[str, Any]] = []
    for value, country in examples:
        requests.append({"kind": "plate", "values": [value], "country": country})
        requests.append({"kind": "plate", "values": [value]})
    requests += [
        {"kind": "plate", "values": ["mh\u00a012 ab1234"], "country": "in"},
        {
            "kind": "plate",
            "values": ["A 123"],
            "country": "NL",
            "series": "historic-geographic",
        },
        {"kind": "plate", "values": ["A 123"], "country": "NL"},
        {"kind": "plate", "values": ["AA 1234"], "country": "ZZ"},
        {"kind": "plate", "values": ["A" * 65], "country": "US"},
        {"kind": "plate", "values": ["A" * 65]},
    ]
    with Geocoder(packs=selection(FIXTURES / "packs/plates-sample")) as geo:
        cases = [
            {
                "id": f"plate-{i:03}",
                "request": r,
                "result": geo.plate(
                    r["values"][0], country=r.get("country"), series=r.get("series")
                ).to_dict(),
            }
            for i, r in enumerate(requests)
        ]
    write(FIXTURES / "plates-vectors.json", "packs/plates-sample", cases)
    print(f"Frozen {len(cases)} plate vectors")


if __name__ == "__main__":
    main()
