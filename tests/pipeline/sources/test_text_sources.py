"""Stream representative text inputs with missing coordinates and honest provenance."""

import gzip
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
import yaml

from pipeline.pins.lock import read_lock
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.runner import run
from pipeline.sources import policy as source_policy

from .fixtures import archive, rows, source_context


def test_country_fallback_and_geonames_subdivisions_are_retained(
    tmp_path: Path,
) -> None:
    reference = [
        "BE",
        "BEL",
        "056",
        "",
        "Belgium",
        "",
        "",
        "",
        "EU",
        ".be",
        "EUR",
        "",
        "32",
        "",
        "",
        "nl,fr,de",
    ]
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "codes",
            {
                "country-codes.csv": (
                    b"ISO3166-1-Alpha-2,CLDR display name\nBE,\n",
                    {},
                ),
                "countryInfo.txt": (("\t".join(reference) + "\n").encode(), {}),
                "admin1CodesASCII.txt": (b"BE.01\tBrussels\tBrussels\t2800866\n", {}),
            },
        )
        run(source.runtime, stages)
        [country] = rows(source, "countries")
        assert country["name"] == "Belgium" and country["numeric"] == "056"
        assert country["license"] == "PDDL-1.0 AND CC-BY-4.0"
        assert (
            json.loads(country["provenance"])["raw"]["geonames_countryInfo"]
            == reference
        )
        [subdivision] = rows(source, "subdivisions")
        assert subdivision["code"] == "BE.01"
        assert subdivision["code_system"] == "GeoNames-admin1"
        assert subdivision["geoname_id"] == "2800866"
        assert subdivision["type"] is None and subdivision["parent_code"] is None


def test_subdivisions_carry_no_lgpl_rows_or_iso_codes(tmp_path: Path) -> None:
    pin = read_lock(REPOSITORY / "pins.lock")["codes"]
    licences = {str(item.metadata["license"]) for item in pin.files}
    assert not any("LGPL" in licence for licence in licences)
    payloads = {
        "README.md": b"# Country codes\n",
        "country-codes.csv": b"ISO3166-1-Alpha-2,CLDR display name\nFR,France\n",
        "countryInfo.txt": b"FR\tFRA\t250\t\tFrance\n",
        "admin1CodesASCII.txt": (
            b"FR.84\tAuvergne-Rh\xc3\xb4ne-Alpes\tAuvergne-Rhone-Alpes\t11071625\n"
            b"FR.11\t\xc3\x8ele-de-France\tIle-de-France\t3012874\n"
        ),
    }
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "codes",
            {
                str(item.metadata["key"]): (
                    payloads[str(item.metadata["key"])],
                    dict(item.metadata),
                )
                for item in pin.files
            },
        )
        run(source.runtime, stages)
        subdivisions = rows(source, "subdivisions")
    assert [row["code"] for row in subdivisions] == ["FR.84", "FR.11"]
    assert {row["code_system"] for row in subdivisions} == {"GeoNames-admin1"}
    assert {row["license"] for row in subdivisions} == {"CC-BY-4.0"}


def test_shared_phone_calling_code_preserves_all_territories(tmp_path: Path) -> None:
    xml = (
        b'<phoneNumberMetadata><territories><territory id="US" countryCode="1"/>'
        b'<territory id="CA" countryCode="1"/></territories></phoneNumberMetadata>'
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "phone",
            {
                "resources/PhoneNumberMetadata.xml": (xml, {}),
                "resources/geocoding/en/1.txt": (b"# fixture\n1202|Washington\n", {}),
            },
        )
        run(source.runtime, stages)
        [row] = rows(source, "phone_prefixes")
        assert row["calling_code"] == "1" and row["country_codes"] == ["US", "CA"]
        assert row["language"] == "en"
        assert len(rows(source, "phone_metadata")) == 2


@pytest.mark.parametrize(
    "name,kind,payloads",
    [
        (
            "airports",
            "airports",
            {
                "airports.csv": (
                    b"ident,name,latitude_deg,longitude_deg,iso_country\nTEST,Example,50.85,4.35,BE\n",
                    {},
                )
            },
        ),
        (
            "postal",
            "postal_codes",
            {
                "BE.zip": (
                    archive(
                        {
                            "BE.txt": (
                                b"BE\t1000\tBrussels\tRegion\t01\t\t\t\t"
                                b"\t50.85\t4.35\t6\n"
                            )
                        }
                    ),
                    {},
                )
            },
        ),
        (
            "unlocode",
            "trade_locations",
            {
                "code-list.csv": (
                    b"Country,Location,Name,Coordinates\n"
                    b"BE,BRU,Brussels,5051N 00421E\n",
                    {},
                )
            },
        ),
        (
            "dbip",
            "ip_ranges",
            {
                "fixture.csv.gz": (
                    gzip.compress(
                        b"1.0.0.0,1.0.0.255,EU,BE,Brussels,Brussels,50.85,4.35\n"
                    ),
                    {"publisher_rows": 1},
                )
            },
        ),
    ],
)
@pytest.mark.parametrize("resolution", [7, 8])
def test_points_use_configured_resolution_and_preserve_country(
    tmp_path: Path,
    name: str,
    kind: str,
    payloads: dict[str, tuple[bytes, dict[str, Any]]],
    resolution: int,
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(tmp_path, ledger, name, payloads)
        source.runtime.config.h3.cell_resolution = resolution
        run(source.runtime, stages)
        [row] = rows(source, kind)
        assert row["country_code"] == "BE" and row["h3_resolution"] == resolution
        for path in (source.normalized / kind).rglob("*.parquet"):
            schema_metadata = pq.read_schema(path).metadata
            assert schema_metadata
            assert (
                schema_metadata[b"h3_reference_resolution"] == str(resolution).encode()
            )
        if name == "dbip":
            assert row["ip_start_packed"] == b"\0" * 12 + b"\x01\x00\x00\x00"
        assert run(source.runtime, stages) == {"completed": 0, "skipped": 2}


def test_plates_match_frozen_wikipedia_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wiki = json.dumps(
        {
            "parse": {
                "revid": 1,
                "text": {
                    "*": "<p>The prefix identifies the district.</p>"
                    "<table><tr><th>Code</th><th>Place</th></tr>"
                    "<tr><th>AA</th><td>North</td></tr></table>"
                },
            }
        }
    ).encode()
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "plates",
            {
                "countries.csv": (
                    b"ISO3166-1-Alpha-2,CLDR display name,wikidata_id\nXY,Example,https://www.wikidata.org/wiki/Q99\n",
                    {"kind": "countries"},
                ),
                "wiki.json": (
                    wiki,
                    {
                        "kind": "wikipedia",
                        "revision": 1,
                        "country_code": "XY",
                        "license": "CC-BY-SA-4.0",
                    },
                ),
            },
        )
        policy = {
            "formats": {},
            "wikidata": {},
            "coverage": {},
            "survey": {
                "XY": {
                    "source": "wiki.json",
                    "classification": "usable_now",
                    "unit_kind": "district",
                    "code_position": "prefix",
                    "evidence_pattern": "The prefix identifies the district",
                }
            },
            "rules": {
                "wiki.json": [
                    {
                        "parser": "table",
                        "tables": [0],
                        "pairs": [[0, 1]],
                        "code_pattern": "[A-Z]{2}",
                        "unit_kind": "district",
                        "series_status": "current",
                    }
                ]
            },
        }
        monkeypatch.setattr(source_policy, "REPOSITORY", tmp_path)
        source.settings.policies = {}
        for name, value in policy.items():
            path = tmp_path / f"{name}.yaml"
            path.write_text(yaml.safe_dump(value))
            source.settings.policies[name] = path.name
        run(source.runtime, stages)
        [row] = rows(source, "plate_codes")
        assert row["code"] == "AA" and row["name_en"] == "North"
        assert row["license"] == "CC-BY-SA-4.0"
        assert rows(source, "plate_survey")[0]["classification"] == "usable_now"
        documents = {row["name"]: row for row in rows(source, "plate_documents")}
        assert set(documents) == {"countries.csv", "wiki.json"}
        wiki_pin = json.loads(documents["wiki.json"]["metadata"])
        assert wiki_pin["revision"] == 1 and wiki_pin["license"] == "CC-BY-SA-4.0"
        assert documents["wiki.json"]["path"].startswith("raw/")
