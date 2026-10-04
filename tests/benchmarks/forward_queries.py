"""Enumerate published sample keys, retaining each verb's required context."""

from dataclasses import dataclass
from typing import Any

from tests.benchmarks.core_read_path import ROOT
from tests.tools.source_fixture import read_source


@dataclass(frozen=True, order=True)
class Query:
    value: str
    options: tuple[tuple[str, str], ...] = ()

    def kwargs(self) -> dict[str, str]:
        return dict(self.options)


def queries(family: str) -> list[Query]:
    """All source keys; plates use all code/country assertions, not full plates."""
    rows = read_source(ROOT / f"tests/fixtures/{family}-source.json.gz")["rows"]
    result: set[Query] = set()
    for row in rows:
        country = (("country", row.get("country_code")),)
        if family == "postal":
            result.add(Query(row["postal_code"], country))
        elif family == "airports":
            for scheme in ("iata", "icao", "gps", "local", "ident"):
                value = row.get(scheme + "_code" if scheme != "ident" else scheme)
                if value:
                    result.add(Query(value, (*country, ("scheme", scheme))))
        elif family == "locode":
            result.add(Query(row["locode"]))
        elif family == "phone":
            prefix = row.get("prefix") or row["calling_code"]
            result.add(Query("+" + prefix + "0" * max(0, 12 - len(prefix))))
        elif family == "ip":
            result.update(Query(row[k]) for k in ("ip_start", "ip_end"))
        elif family == "plates":
            if row.get("code"):
                result.add(Query(row["code"], country))
        else:
            result.update(Query(row[k], country) for k in ("name", "name_en") if row[k])
    return sorted(result)


def misses(family: str) -> list[Query]:
    """Syntactically valid absent keys, verified by the runner before timing."""
    values: dict[str, list[Query]] = {
        "postal": [Query("ZZ999999", (("country", c),)) for c in ("BE", "NL", "US")],
        "airports": [Query("ZZZ"), Query("ZZZZ")],
        "locode": [Query("BEZZZ"), Query("NLZZZ")],
        "phone": [Query("+999123456789")],
        "ip": [Query("0.0.0.0"), Query("ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff")],
        "plates": [Query("QQQQQQQQQQQQQQQQQQQQ")],
        "geocode": [Query("Zqxjkvwqzqxjkvwq"), Query("Qzxvjkqzxvjk")],
    }
    return values[family]


def airport_defaults() -> list[Query]:
    rows: list[dict[str, Any]] = read_source(
        ROOT / "tests/fixtures/airports-source.json.gz"
    )["rows"]
    return sorted(
        {Query(r[k]) for r in rows for k in ("iata_code", "icao_code") if r[k]}
    )
