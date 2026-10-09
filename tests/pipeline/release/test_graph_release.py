"""The synthetic production graph runs through dataset and every pack family."""

import ipaddress
import json
from pathlib import Path
from typing import Any

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.engines.artifact_io import file_record
from pipeline.release import pins as release_pins
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.runtime.records import Recipe
from pipeline.sources.shared.lookup_schemas import LOOKUP_SCHEMAS
from pipeline.stages.contract import Context, make_unit
from pipeline.stages.registry import ordered, registry
from thereabouts import Geocoder, _core

from ..geographic_fixtures import build, geographic_graph, partition, source_receipts
from ..helpers import SyntheticStage
from ..test_names import alias
from ..test_names_plates_graph import plates_receipt

FAMILIES = ("core", "postal", "airports", "locode", "phone", "ip", "plates")
Row = dict[str, Any]


def point(lat: float, lon: float) -> Row:
    cell = h3.latlng_to_cell(lat, lon, 8)
    return {
        "latitude": lat,
        "longitude": lon,
        "h3": cell,
        "h3_uint64": int(cell, 16),
        "h3_resolution": 8,
    }


def address(text: str) -> bytes:
    return ipaddress.ip_address(text).packed.rjust(16, b"\0")


# One observation per lookup kind, all in ZZ at the synthetic town (0, 0).
LOOKUPS: dict[str, dict[str, list[Row]]] = {
    "codes": {
        "countries": [{"country_code": "ZZ", "alpha3": "ZZZ", "name": "Zedland"}],
        "subdivisions": [],
    },
    "phone": {
        "phone_metadata": [
            {
                "territory": "ZZ",
                "calling_code": "999",
                "metadata_xml": '<territory id="ZZ" countryCode="999">'
                "<fixedLine><nationalNumberPattern>1\\d{6}</nationalNumberPattern>"
                "</fixedLine></territory>",
            }
        ],
        "phone_prefixes": [
            {
                "prefix": "9991",
                "calling_code": "999",
                "language": "en",
                "description": "Town",
                "country_codes": ["ZZ"],
            }
        ],
    },
    "timezones": {
        "timezone_cells": [
            {
                "tzid": "Etc/UTC",
                "h3": h3.latlng_to_cell(0, 0, 3),
                "h3_uint64": int(h3.latlng_to_cell(0, 0, 3), 16),
                "h3_resolution": 3,
            }
        ],
        "zone_tables": [
            {"table": "zone.tab", "tzid": "Etc/UTC", "country_codes": "ZZ"}
        ],
    },
    "postal": {
        "postal_codes": [
            {"country_code": "ZZ", "postal_code": "00001", "place_name": "Town"}
            | point(0.0, 0.0)
        ]
    },
    "airports": {
        "airports": [
            {
                "ident": "ZZTW",
                "iata_code": "ZZT",
                "icao_code": "ZZTW",
                "type": "small_airport",
                "name": "Town Airport",
                "country_code": "ZZ",
            }
            | point(0.01, 0.01)
        ]
    },
    "unlocode": {
        "trade_locations": [
            {"locode": "ZZTWN", "country_code": "ZZ", "location": "TWN", "name": "Town"}
            | point(0.0, 0.0)
        ]
    },
    "dbip": {
        "ip_ranges": [
            {
                "ip_start": "203.0.113.0",
                "ip_end": "203.0.113.255",
                "country_code": "ZZ",
                "city": "Town",
                "ip_version": 4,
                "ip_start_packed": address("203.0.113.0"),
                "ip_end_packed": address("203.0.113.255"),
            }
            | point(0.0, 0.0)
        ]
    },
}


def lookup_receipts(ctx: Context, normalized: SyntheticStage, ledger: Ledger) -> None:
    """Normalized receipts for every static and spatial lookup source."""
    for source, kinds in LOOKUPS.items():
        ctx.config.sources[source].enabled = True
        parts, paths = [], []
        for kind, rows in kinds.items():
            schema = LOOKUP_SCHEMAS[kind]  # type: ignore[index]
            filled = [
                {
                    "source": source,
                    "source_id": f"{kind}:{number}",
                    "source_release": "test",
                    "license": "Public-Domain",
                    "provenance": "{}",
                }
                | row
                for number, row in enumerate(rows)
            ]
            path = partition(ctx.root, source, kind)
            pq.write_table(pa.Table.from_pylist(filled, schema=schema), path)
            paths.append(path)
            parts.append(
                {**file_record(ctx.root, path), "kind": kind, "rows": len(rows)}
            )
        manifest = ctx.root / "normalized" / source / "manifest.json"
        write_json(manifest, {"source": source, "partitions": parts})
        recipe = Recipe("normalize", source)
        normalized.recipes.append(recipe)
        unit = make_unit(ctx, recipe, normalized.identity(ctx))
        ledger.register(recipe)
        ledger.complete(
            *recipe.key,
            unit.inputs_hash,
            [manifest, *paths],
            metadata={
                "identity": unit.identity,
                "dependency_hash": unit.dependency_hash,
            },
        )


def test_lookups_dataset_and_packs_with_the_real_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The synthetic receipts are not the pinned inputs; test_pins covers the check.
    monkeypatch.setattr(release_pins, "verify", lambda *args: None)
    town = [alias("900", "1", "Stadt", language="de")]
    with Ledger(tmp_path / "workspace", None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path / "workspace", ledger, names=town)
        plates_receipt(ctx, normalized, ledger)
        lookup_receipts(ctx, normalized, ledger)
        release = ctx.config.release
        release.enabled, release.version = True, "2026.10"
        release.acceptance.ocean_points = 50
        stages = geographic_graph(ctx, normalized) + [
            stage
            for stage in registry(ctx.config)
            if stage.name in {"dataset", "packs"}
        ]
        build(ctx, ordered(stages), "packs")
        packs = located(ctx.root, ctx.config.paths.packs) / "2026.10"
        index = json.loads((packs / "index.json").read_text())
        assert set(index["datasets"]["2026.10"]["packs"]) == set(FAMILIES)
        checks: dict[str, Row] = {}
        for family in FAMILIES:
            assert _core.verify_pack(str(packs / family))["family"] == family
            report = json.loads((packs / f"acceptance/{family}.json").read_text())
            assert report["passed"], family
            checks |= report["checks"]
        # Every sampled check had something to check, not just vectors.
        for name in ("reverse", "names", "alternate_names", "postal", "locode"):
            assert checks[name]["agreed"] >= 1, name
        for name in ("airports_iata", "airports_icao", "ip_v4", "phone", "vectors"):
            assert checks[name]["agreed"] >= 1, name
        selection = {family: packs / family for family in FAMILIES}
        with Geocoder(packs=selection) as geo:
            found = geo.reverse(lat=0.0, lon=0.0)
            assert found.status == "matched" and found.city is not None
            assert found.city.name == "Town" and found.timezone == "Etc/UTC"
            named = geo.geocode("Stadt")
            assert named.city is not None and named.city.id == found.city.id
            postal = geo.postal("00001", country="ZZ")
            assert postal.city is not None and postal.city.id == found.city.id
            assert geo.ip("203.0.113.7").country is not None
