"""A complete synthetic release dataset: every table, closed, all seven families.

The skill rows (Paris, Antwerp, Brussels, Mountain View, ...) plus names and the
plate tables exactly as the plate-country engine writes them.
"""

from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.config import Config, load
from pipeline.engines.artifact_io import file_record
from pipeline.engines.plate_country import formats, tables
from pipeline.engines.plate_country.documents import Pool
from pipeline.engines.plate_country.policy import policy
from pipeline.release.assemble import assemble
from pipeline.release.dataset_schema import inputs
from pipeline.release.dataset_schema import load as schema
from pipeline.release.source import external
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.resources import ResourceGuard
from tests.skill.dataset import DEFAULTS, PARIS, ROWS, arrow_type

Row = dict[str, Any]
PIN = {
    "url": "https://example.invalid/wiki-FR.json",
    "license": "CC-BY-SA-4.0",
    "source": "plates",
}


def plate_rows(root: Path) -> list[Row]:
    """The plate tables exactly as the plate-country engine writes them."""
    rule = dict(
        country_code="FR",
        series_id="ordinary",
        series_status="current",
        pattern="[A-Z]{2}-[0-9]{3}-[A-Z]{2} (?P<code>[0-9]{2})",
        code_group="code",
    )
    grammar = [formats._decorate(rule, "wiki-FR.json", PIN)]
    code = dict(
        source="plates",
        country_code="FR",
        code="75",
        name_en="Paris",
        unit_kind="department",
        scope="registration_unit",
        series_status="current",
        subdivision_codes='["FR-75C"]',
        source_url=PIN["url"],
        license="CC-BY-SA-4.0",
    )
    pins = Pool({})
    pins.used["wiki-FR.json"] = PIN
    return [
        tables.write(root, root / "plates", kind, rows, 16)
        for kind, rows in (
            ("plate_formats", tables.formats(grammar, pins)),
            ("plate_codes", tables.codes([code])),
            ("plate_policy", tables.policy(policy("inference"))),
            ("plate_priors", tables.priors([])),
        )
    ]


def names_rows() -> list[Row]:
    return [
        {
            "city_id": PARIS,
            "name": "Lutetia",
            "kind": "alternate",
            "language": "la",
            "country_code": "FR",
            "place_id": PARIS,
            "source": "geonames",
            "source_id": "1",
            "source_release": "test",
            "license": "CC-BY-4.0",
            "provenance": "{}",
        }
    ]


# The configured source of each forward table, for rows the skill leaves unset.
SOURCES = {
    "postal_codes": "postal",
    "airports": "airports",
    "trade_locations": "unlocode",
    "ip_ranges": "dbip",
    "phone_prefixes": "phone",
    "phone_metadata": "phone",
}


def snapshot(root: Path) -> Path:
    """Every table of config/dataset.yaml; cells split by block like lookups."""
    description = inputs(schema(REPOSITORY / "config/dataset.yaml"))
    records = plate_rows(root)
    rows = ROWS | {"names": names_rows()}
    for kind, value in description.items():
        if kind.startswith("plate_"):
            continue
        arrow = pa.schema(
            [
                pa.field(c["name"], arrow_type(c["type"]), nullable=c["nullable"])
                for c in value["columns"]
            ]
        )
        required = {c["name"]: c["type"] for c in value["columns"] if not c["nullable"]}
        # Observed sources must be configured ones; the skill rows leave them unset.
        defaults = {k: DEFAULTS[t] for k, t in required.items()}
        if "source" in defaults:
            defaults["source"] = "geonames"
        filled = [defaults | r for r in rows.get(kind, [])]
        if kind in SOURCES:
            filled = [
                {"source": SOURCES[kind], "source_id": f"{kind}:{i}"}
                | {k: v for k, v in row.items() if v is not None}
                for i, row in enumerate(filled)
            ]
        groups: dict[str, list[Row]] = {"": filled}
        if kind == "cells":
            # The writer stores no cell beneath another stored cell.
            stored = {row["h3_uint64"] for row in filled}
            filled = [
                row
                for row in filled
                if not any(
                    h3.cell_to_parent(row["h3_uint64"], level) in stored
                    for level in range(row["h3_resolution"])
                )
            ]
            groups = {}
            for row in filled:
                block = f"{h3.cell_to_parent(row['h3_uint64'], 3):x}"
                groups.setdefault(block, []).append(row)
        for block, group in groups.items():
            path = root / kind / f"{block or 'part'}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist(group, schema=arrow), path)
            record = {**file_record(root, path), "kind": kind, "rows": len(group)}
            if block:
                record["block"] = block
            records.append(record)
    write_json(
        root / "manifest.json",
        {
            "completed": True,
            "tables": records,
            "reference_resolution": 8,
            "block_resolution": 3,
            "normalization": {
                "completed": True,
                "policy": {"distant_m": 25000, "nearest_m": 50000},
            },
        },
    )
    return root


def dataset(root: Path) -> tuple[Path, Config]:
    """Assemble the synthetic snapshot into ``root/dataset/2026.10``."""
    config = load()
    config.release.enabled = True
    config.release.version = "2026.10"
    source = snapshot(root / "input")
    output = root / "dataset/2026.10"
    guard = ResourceGuard(root, config.resources)
    assemble(external(source, config.h3), output, config, guard, "identity")
    return output, config
