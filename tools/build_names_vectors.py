"""Freeze city-name vectors; independent source/ranking assertions run in pytest."""

from typing import Any

from thereabouts import Geocoder
from tools.build_forward_vectors import FIXTURES, write
from tools.source_fixture import read_source


def main() -> None:
    source = read_source(FIXTURES / "geocode-source.json.gz")
    seen: dict[str, int] = {}
    requests: list[dict[str, Any]] = []
    for row in source["rows"]:
        country = row["country_code"]
        if seen.get(country, 0) < 3:
            requests.append(
                {"kind": "geocode", "values": [row["name"]], "country": country}
            )
            seen[country] = seen.get(country, 0) + 1
    examples: list[tuple[str, dict[str, Any]]] = [
        ("Springfield", {}),
        ("Springfield", {"limit": 1}),
        ("Springfield", {"country": "US", "subdivision": "US-IL"}),
        ("Springfield", {"country": "FR"}),
        ("Springfield", {"prefer": "population"}),
        ("Springfield", {"limit": 100}),
        ("Pariss", {"country": "FR"}),
        ("Sprngfield", {}),
        ("Amster", {"country": "NL"}),
        ("St. Etienne", {"country": "FR"}),
        ("Ｓt. Étienne", {"country": "FR"}),  # noqa: RUF001 -- NFKC case
        ("BRUSSELS", {"country": "be"}),
        ("Mumbai", {"subdivision": "FR-IDF"}),
        ("Paris", {"limit": 0}),
        ("Paris", {"limit": 101}),
        ("Paris", {"prefer": "nearest"}),
        ("Paris", {"scope": "places"}),
        ("Lyon", {}),
        ("No such city qzxw", {}),
        ("", {}),
        ("75001", {}),
        ("8.8.8.8", {}),
        ("+44", {}),
        ("CDG", {}),
        ("INBOM", {}),
        ("12 Main Street", {}),
        ("10 Downing St", {}),
        ("SW1A1AA", {}),
        ("MH12AB1234", {}),
        ("8860145b49fffff", {}),
        ("Karakulam", {"country": "IN"}),
    ]
    requests += [
        {"kind": "geocode", "values": [name], **kwargs} for name, kwargs in examples
    ]
    synthetic = [
        {"kind": "geocode", "values": [name]}
        for name in [
            "München 東京",
            "munchen 東京",
            "Munich Tokyo",
            "Minga Tokyo",
            "Ming Tokyo",
            "東京",
            "12345",
        ]
    ]
    for pack, queries, name in [
        ("core-names-sample", requests, "geocode-vectors.json"),
        ("core-names-synthetic", synthetic, "geocode-synthetic-vectors.json"),
    ]:
        with Geocoder(FIXTURES / "packs" / pack) as geo:
            cases = []
            for i, r in enumerate(queries):
                kwargs = {k: v for k, v in r.items() if k not in {"kind", "values"}}
                cases.append(
                    {
                        "id": f"{pack}-{i:03}",
                        "request": r,
                        "result": geo.geocode(r["values"][0], **kwargs).to_dict(),
                    }
                )
        write(FIXTURES / name, "packs/" + pack, cases)
        print(name, len(cases))


if __name__ == "__main__":
    main()
