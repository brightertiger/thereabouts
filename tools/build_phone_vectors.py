"""Freeze shared phone vectors; source assertions remain independent."""

from tests.conformance.pack_selection import selection
from thereabouts import Geocoder
from tools.build_forward_vectors import FIXTURES, write
from tools.source_fixture import read_source


def main() -> None:
    source = read_source(FIXTURES / "phone-source.json.gz")
    chosen: dict[str, set[str]] = {}
    requests = []
    for row in source["rows"]:
        code = row["prefix"] or row["calling_code"]
        for country in row["country_codes"]:
            codes = chosen.setdefault(country, set())
            if code not in codes and len(codes) < 3:
                codes.add(code)
                requests.append(
                    {
                        "kind": "phone",
                        "values": ["+" + (code + "5551234")[:15]],
                        "country": country,
                    }
                )
    requests += [
        {"kind": "phone", "values": [number]}
        for number in [
            "+91 (22) 1234-5678",
            "+91 (22) 2345-6789",
            "+352",
            "+1",
            "+999123",
            "12025551234",
            "",
            "+0123",
            "++33123456789",
            "+１２３",  # noqa: RUF001 -- deliberately invalid E.164 digits
            "+1234567890123456",
            "+1 x123",
            "+33\0",
        ]
    ]
    for pack, queries in [
        ("phone-sample", requests),
        (
            "phone-synthetic",
            [
                {"kind": "phone", "values": [n]}
                for n in ["+1", "+12025551234", "+120999", "+129999", "+44", "123"]
            ],
        ),
    ]:
        with Geocoder(packs=selection(FIXTURES / "packs" / pack)) as geo:
            cases = [
                {
                    "id": f"{pack}-{i:03}",
                    "request": r,
                    "result": geo.phone(r["values"][0]).to_dict(),
                }
                for i, r in enumerate(queries)
            ]
        name = (
            "phone-vectors.json"
            if pack.endswith("sample")
            else "phone-synthetic-vectors.json"
        )
        write(FIXTURES / name, "packs/" + pack, cases)
        print(name, len(cases))


if __name__ == "__main__":
    main()
