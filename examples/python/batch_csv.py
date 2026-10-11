"""Run every sample CSV in examples/data through its lookup and print a match table.

Needs: thereabouts data install core postal airports ip locode phone plates
Run:   python examples/python/batch_csv.py [--data-dir DIR] [--csv-dir DIR] [--limit N]
Each row is compared with its expected answer. A mismatch is printed, never raised.
"""

import argparse
import csv
from pathlib import Path

from thereabouts import DataNotInstalledError, Geocoder, GeocoderError

DEFAULT_CSV_DIR = Path(__file__).resolve().parent.parent / "data"


def countries(result) -> set[str]:
    """Country codes of the result, including every ambiguous candidate."""
    found = {result.country.code} if result.country else set()
    found |= {c.country.code for c in result.candidates if c.country}
    return found


def verdict(result, expected_country: str) -> str:
    if expected_country == "":
        # reserved ranges: not_found, or (release 2026.10) matched with no country
        return (
            "ok"
            if result.status == "not_found" or not countries(result)
            else "MISMATCH"
        )
    if result.status == "matched" and expected_country in countries(result):
        return "ok"
    if result.status == "ambiguous" and expected_country in countries(result):
        return "ok (ambiguous)"
    return "MISMATCH"


def place(result) -> str:
    if result.city:
        return result.city.name
    return result.country.name if result.country else "-"


def city_points(geo, rows):
    points = [{"lat": float(r["lat"]), "lon": float(r["lon"])} for r in rows]
    for row, result in zip(rows, geo.reverse_many(points), strict=True):
        accepted = {
            row["expected_city"],
            *filter(None, row["accepted_names"].split("|")),
        }
        got = result.city.name if result.city else None
        code = result.country.code if result.country else None
        ok = got in accepted and code == row["expected_country"]
        yield (
            row["id"],
            row["expected_city"],
            f"{got}/{code}",
            "ok" if ok else "MISMATCH",
        )


def forward(call, key, expected_label, country_key="expected_country"):
    def run(geo, rows):
        for row in rows:
            result = call(geo, row)
            joined = ",".join(sorted(countries(result))) or "-"
            yield (
                row[key],
                row[expected_label],
                f"{result.status}: {place(result)}/{joined}",
                verdict(result, row[country_key]),
            )

    return run


FAMILIES = {
    "city_points.csv": city_points,
    "postal.csv": forward(
        lambda g, r: g.postal(r["code"], country=r["country"]),
        "code",
        "expected_city",
        country_key="country",
    ),
    "airports.csv": forward(
        lambda g, r: g.airport(r["code"], scheme=r["scheme"]),
        "code",
        "expected_name_contains",
    ),
    "locode.csv": forward(lambda g, r: g.locode(r["code"]), "code", "expected_name"),
    "phone.csv": forward(
        lambda g, r: g.phone(r["number"]), "number", "expected_country"
    ),
    "ip.csv": forward(lambda g, r: g.ip(r["address"]), "address", "note"),
    "plates.csv": forward(
        lambda g, r: g.plate(r["plate"]), "plate", "expected_country"
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--data-dir",
        default=None,
        help="store directory (default: the client's default store)",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=DEFAULT_CSV_DIR,
        help="folder holding the sample CSV files",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="rows to read from each file"
    )
    args = parser.parse_args()

    totals = {"ok": 0, "MISMATCH": 0}
    with Geocoder(data_dir=args.data_dir) as geo:
        for name, handler in FAMILIES.items():
            path = args.csv_dir / name
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))[: args.limit]
            print(f"\n== {name} ({len(rows)} rows) ==")
            print(f"{'input':<22} {'expected':<26} {'got':<40} verdict")
            try:
                for key, expected, got, status in handler(geo, rows):
                    totals["ok" if status.startswith("ok") else "MISMATCH"] += 1
                    print(f"{key[:22]:<22} {expected[:26]:<26} {got[:40]:<40} {status}")
            except DataNotInstalledError as exc:
                print(f"(skipped, pack not installed: {exc})")
            except GeocoderError as exc:
                print(f"(error: {exc})")
    print(f"\nsummary: {totals['ok']} ok, {totals['MISMATCH']} mismatch")


if __name__ == "__main__":
    main()
