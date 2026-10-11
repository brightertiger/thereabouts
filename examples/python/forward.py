"""Forward lookups: names, postal codes, airports, UN/LOCODEs, phone numbers, IPs, plates.

Needs: thereabouts data install core postal airports ip locode phone plates
Run:   python examples/python/forward.py [--data-dir DIR]
A family that is not installed is reported and skipped.
"""

import argparse

from thereabouts import DataNotInstalledError, Geocoder, GeocoderError


def line(result) -> str:
    city = result.city.name if result.city else None
    country = result.country.code if result.country else None
    text = f"{result.status:<13} match={result.match} city={city} country={country}"
    if result.candidates:
        shown = ", ".join(
            f"{c.city.name if c.city else '?'}/{c.country.code if c.country else '?'}"
            for c in result.candidates[:4]
        )
        text += f" | {len(result.candidates)} candidates (ranked by {result.rank_basis}): {shown}"
    if result.hint:
        text += f" | hint: {result.hint}"
    return text


def section(title: str, calls) -> None:
    """Run (label, callable) pairs and keep going when a family is missing."""
    print(f"\n== {title} ==")
    for label, call in calls:
        try:
            print(f"{label:<34} {line(call())}")
        except DataNotInstalledError as exc:
            print(f"(skipped, pack not installed: {exc})")
            return
        except GeocoderError as exc:
            print(f"{label:<34} error: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=None, help="store directory (default: the client's default store)")
    args = parser.parse_args()

    with Geocoder(data_dir=args.data_dir) as geo:
        section("geocode: towns and cities by name (no street addresses)", [
            ("Paris, FR", lambda: geo.geocode("Paris", country="FR")),
            ("Springfield (ambiguous)", lambda: geo.geocode("Springfield", country="US", limit=5)),
            ("Springfield, prefer population", lambda: geo.geocode("Springfield", country="US", prefer="population")),
            ("Pariss (fuzzy)", lambda: geo.geocode("Pariss", country="FR")),
            ("12 Main Street", lambda: geo.geocode("12 Main Street")),
        ])
        section("postal: the country is required", [
            ("75001, FR", lambda: geo.postal("75001", country="FR")),
            ("10001, US", lambda: geo.postal("10001", country="US")),
            ("10001 without country", lambda: geo.postal("10001")),
        ])
        section("airport: IATA then ICAO unless a scheme is given", [
            ("CDG", lambda: geo.airport("CDG")),
            ("LHR, scheme=iata", lambda: geo.airport("LHR", scheme="iata")),
            ("KJFK, scheme=icao", lambda: geo.airport("KJFK", scheme="icao")),
        ])
        section("locode: five characters, or three plus a country", [
            ("BEANR", lambda: geo.locode("BEANR")),
            ("ANR, country=BE", lambda: geo.locode("ANR", country="BE")),
        ])
        section("phone: international E.164 with a leading +", [
            ("+32 2 555 1234", lambda: geo.phone("+32 2 555 1234")),
            ("+1 415 555 2671 (shared code)", lambda: geo.phone("+1 415 555 2671")),
            ("0032 2 555 1234 (no plus)", lambda: geo.phone("0032 2 555 1234")),
        ])
        section("ip: IPv4 or IPv6 literal", [
            ("8.8.8.8", lambda: geo.ip("8.8.8.8")),
            ("2001:4860:4860::8888", lambda: geo.ip("2001:4860:4860::8888")),
            ("192.0.2.1 (documentation)", lambda: geo.ip("192.0.2.1")),
        ])
        section("plate: format evidence, not a register", [
            ("VU52 BWO", lambda: geo.plate("VU52 BWO")),
            ("05-GJV-1", lambda: geo.plate("05-GJV-1")),
            ("05-GJV-1, country=NL", lambda: geo.plate("05-GJV-1", country="NL")),
            ("SCF 6045P", lambda: geo.plate("SCF 6045P")),
        ])


if __name__ == "__main__":
    main()
