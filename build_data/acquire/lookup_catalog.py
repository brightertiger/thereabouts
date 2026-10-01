"""Reviewed, explicitly pinned releases for the additional lookup adapters."""

from typing import Any

LOOKUP_SOURCES = (
    "postal",
    "codes",
    "airports",
    "unlocode",
    "timezones",
    "phone",
    "dbip",
)
CC_BY = "https://creativecommons.org/licenses/by/4.0/"
PDDL = "https://opendatacommons.org/licenses/pddl/1-0/"
PHONE_COMMIT = "0ae309f1940227efe688f5eb1815ef45a6fbee8d"
CODES_COMMIT = "2e9d6498a0456f4afc2f6cf367d1e12a9ed4afe1"
ISO_COMMIT = "4c6a69927a25326a69bf753671fb571bb437cd7d"
LOCODE_COMMIT = "b1309b37edea63334a819a78c22b8967f61c37ad"
RAW = "https://raw.githubusercontent.com/"


def spec(url: str, license: str, license_url: str, attribution: str) -> dict[str, Any]:
    return dict(
        url=url, license=license, license_url=license_url, attribution=attribution
    )


def catalog(source: str) -> dict[str, dict[str, Any]]:
    """Only phone's file list needs discovery; its entire git tree is pinned."""
    if source == "postal":
        return {
            name: spec(
                "https://download.geonames.org/export/zip/" + name,
                "CC-BY-4.0",
                CC_BY,
                "GeoNames; GB contains Royal Mail copyright and database right 2022",
            )
            for name in (
                "allCountries.zip",
                "GB_full.csv.zip",
                "NL_full.csv.zip",
                "CA_full.csv.zip",
                "readme.txt",
            )
        }
    if source == "airports":
        return {
            "airports.csv": spec(
                "https://davidmegginson.github.io/ourairports-data/airports.csv",
                "Public-Domain",
                "https://ourairports.com/data/",
                "OurAirports contributors",
            )
        }
    if source == "dbip":
        return {
            "dbip-city-lite-2026-10.csv.gz": {
                **spec(
                    "https://download.db-ip.com/free/dbip-city-lite-2026-10.csv.gz",
                    "CC-BY-4.0",
                    CC_BY,
                    "IP Geolocation by DB-IP https://db-ip.com",
                ),
                "publisher_rows": 7786864,
                "publisher_md5": "443ac78aef7767e461b9e43317ee168a",
                "publisher_count_url": "https://db-ip.com/db/download/ip-to-city-lite",
            }
        }
    if source == "unlocode":
        base = f"{RAW}datasets/un-locode/{LOCODE_COMMIT}/"
        return {
            name: spec(base + path, "PDDL-1.0", PDDL, "UNECE; DataHub maintainers")
            for name, path in (
                ("code-list.csv", "data/code-list.csv"),
                ("README.md", "README.md"),
                ("datapackage.json", "datapackage.json"),
                ("function-classifiers.csv", "data/function-classifiers.csv"),
            )
        }
    if source == "timezones":
        base = "https://github.com/evansiroky/timezone-boundary-builder/releases/download/2026d/"
        return {
            "timezones-with-oceans.shapefile.zip": spec(
                base + "timezones-with-oceans.shapefile.zip",
                "ODbL-1.0",
                "https://opendatacommons.org/licenses/odbl/1-0/",
                "timezone-boundary-builder; OpenStreetMap contributors",
            ),
            "timezone-names-with-oceans.json": spec(
                base + "timezone-names-with-oceans.json",
                "ODbL-1.0",
                "https://opendatacommons.org/licenses/odbl/1-0/",
                "timezone-boundary-builder; OpenStreetMap contributors",
            ),
            "tzdata2026e.tar.gz": spec(
                "https://data.iana.org/time-zones/releases/tzdata2026e.tar.gz",
                "Public-Domain",
                "https://data.iana.org/time-zones/tz-link.html",
                "IANA Time Zone Database contributors",
            ),
        }
    if source == "codes":
        base = f"{RAW}datasets/country-codes/{CODES_COMMIT}/"
        iso = f"{RAW}pycountry/pycountry/{ISO_COMMIT}/"
        return {
            "country-codes.csv": spec(
                base + "data/country-codes.csv",
                "PDDL-1.0",
                PDDL,
                "DataHub; UN Statistics Division; GeoNames; CLDR",
            ),
            "README.md": spec(
                base + "README.md", "PDDL-1.0", PDDL, "DataHub maintainers"
            ),
            "iso3166-2.json": spec(
                iso + "src/pycountry/databases/iso3166-2.json",
                "LGPL-2.1-or-later",
                iso + "LICENSE.txt",
                "Debian iso-codes; pycountry",
            ),
            "iso-LICENSE.txt": spec(
                iso + "LICENSE.txt",
                "LGPL-2.1-or-later",
                iso + "LICENSE.txt",
                "Debian iso-codes; pycountry",
            ),
            **{
                name: spec(
                    "https://download.geonames.org/export/dump/" + name,
                    "CC-BY-4.0",
                    CC_BY,
                    "GeoNames",
                )
                for name in ("countryInfo.txt", "admin1CodesASCII.txt")
            },
        }
    if source == "phone":
        from .lookup_http import get_json

        tree = get_json(
            f"https://api.github.com/repos/google/libphonenumber/git/trees/{PHONE_COMMIT}?recursive=1"
        )
        if tree.get("truncated"):
            raise ValueError("Incomplete libphonenumber git tree")
        base = f"{RAW}google/libphonenumber/{PHONE_COMMIT}/"
        return {
            item["path"]: {
                **spec(
                    base + item["path"],
                    "Apache-2.0",
                    base + "LICENSE",
                    "The Libphonenumber Authors; Google",
                ),
                "git_blob": item["sha"],
            }
            for item in tree["tree"]
            if item["type"] == "blob"
            and (
                item["path"].startswith("resources/geocoding/")
                or item["path"] in ("resources/PhoneNumberMetadata.xml", "LICENSE")
            )
        }
    raise ValueError(f"Unknown lookup source: {source}")
