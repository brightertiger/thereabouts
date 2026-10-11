"""Reverse geocoding: coordinates and H3 cells to country, state, city and timezone.

Needs the core pack:  thereabouts data install core
Run:                  python examples/python/reverse.py [--data-dir DIR]
"""

import argparse
import json

from thereabouts import DataNotInstalledError, Geocoder

PLACES = [
    ("Eiffel Tower, Paris", 48.8584, 2.2945),
    ("Shinjuku, Tokyo", 35.6896, 139.7006),
    ("Brooklyn Bridge, New York", 40.7061, -73.9969),
    ("Gateway of India, Mumbai", 18.9220, 72.8347),
    ("Howrah Bridge, Howrah", 22.5851, 88.3468),
    ("Arabian Sea, off Mumbai", 19.0, 72.6),
]


def line(result) -> str:
    """One readable line for a result; nulls stay null."""
    city = result.city.name if result.city else None
    state = result.state.name if result.state else None
    country = result.country.code if result.country else None
    return (
        f"{result.status:<13} match={result.match} city={city} state={state} "
        f"country={country} tz={result.timezone}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=None, help="store directory (default: the client's default store)")
    args = parser.parse_args()

    try:
        geo = Geocoder(data_dir=args.data_dir)
    except DataNotInstalledError as exc:
        raise SystemExit(f"Data missing: {exc}")

    with geo:
        print("== reverse(lat=, lon=) ==")
        for name, lat, lon in PLACES:
            print(f"{name:<28} {line(geo.reverse(lat=lat, lon=lon))}")

        print("\n== a nearest or distant match reports a distance band ==")
        remote = geo.reverse(lat=46.5, lon=-109.5)  # rural Montana
        print(line(remote), "| band:", remote.distance_band)

        print("\n== evidence explains the answer (or the miss) ==")
        ocean = geo.reverse(lat=19.0, lon=72.6, evidence=True)
        print(line(ocean), "| reason:", ocean.evidence.reason)

        print("\n== invalid input is a result, not an exception ==")
        bad = geo.reverse(lat=95.0, lon=0.0)
        print(line(bad), "| hint:", bad.hint)

        print("\n== from_h3: the stored ancestor of a cell (resolution 0 to 8) ==")
        paris = geo.reverse(lat=48.8566, lon=2.3522)
        print("cell of Paris centre:", paris.cell)
        print(line(geo.from_h3(paris.cell)))
        print(line(geo.from_h3("881fb46625fffff")))

        print("\n== reverse_many: named lat/lon mappings, results in order ==")
        points = [{"lat": lat, "lon": lon} for _, lat, lon in PLACES[:3]]
        for point, result in zip(points, geo.reverse_many(points)):
            print(point, "->", result.city.name if result.city else None)

        print("\n== the full JSON contract of one result ==")
        print(json.dumps(geo.reverse(lat=48.8584, lon=2.2945).to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
