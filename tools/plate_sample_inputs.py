"""Read plate evidence without running acquisition or normalization stages."""

import json
import unicodedata
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from build_data.acquire.plates_config import policy as base_policy
from build_data.acquire.plates_html import clean_text
from build_data.acquire.plates_reader import document
from build_data.plate_country.formats import _decorate
from build_data.plate_country.policy import code_key, policy
from build_data.plate_country.syntax import template_pattern
from tools.build_sample_pack import sha
from tools.forward_sample import COUNTRIES

CODE_FIELDS = (
    "country_code",
    "code",
    "name_en",
    "name_local",
    "unit_kind",
    "scope",
    "series_status",
    "subdivision_scope",
    "subdivision_codes",
    "source_url",
    "license",
)


def selected_codes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: dict[str, set[str]] = {c: set() for c in COUNTRIES}
    output = []
    entity_seen: set[tuple[str, str]] = set()
    for row in rows:
        country = row["country_code"]
        if country not in COUNTRIES:
            continue
        code = code_key(row["code"])
        if len(chosen[country]) < 32 or code in {
            "MH",
            "MH12",
            "DL",
            "DL01",
            "34",
            "06",
            "A",
        }:
            chosen[country].add(code)
        if code in chosen[country]:
            if row["scope"] == "entity_association":
                if (country, code) in entity_seen:
                    continue
                entity_seen.add((country, code))
            output.append(row)
    return output


def load(
    data: Path, normalized: Path
) -> tuple[dict[str, Any], dict[str, str], int, str]:
    inputs = {}
    if (normalized / "manifest.json").exists():
        manifest = json.loads((normalized / "manifest.json").read_text())
        inputs[str(normalized / "manifest.json")] = sha(normalized / "manifest.json")
        for artifact in manifest["outputs"]:
            path = normalized / artifact["file"]
            digest = sha(path)
            if digest != artifact["sha256"]:
                raise ValueError(f"Corrupt plate input: {path}")
            inputs[str(path)] = digest
        bundle = json.loads((normalized / manifest["bundle"]).read_text())
        total = len(bundle["codes"]) + len(bundle["formats"]) + len(bundle["priors"])
        bundle["codes"] = selected_codes(bundle["codes"])
        bundle["formats"] = [
            r for r in bundle["formats"] if r["country_code"] in COUNTRIES
        ]
        mode = "normalized plates_country"
    else:
        bundle, total = base_inputs(data, inputs)
        mode = (
            "base plates plus committed rules; "
            "plate-country tables and vehicle priors absent"
        )
    for row in bundle["codes"]:
        codes = row.get("subdivision_codes") or []
        row["subdivision_codes"] = (
            json.loads(codes) if isinstance(codes, str) else codes
        )
    bundle["policy"]["decimal_zeroes"] = [
        n for n in range(0x110000) if unicodedata.decimal(chr(n), None) == 0
    ]
    bundle["policy"]["decimal_unicode_version"] = unicodedata.unidata_version
    for path in Path("build_data/plate_country/data").glob("*.json"):
        inputs[str(path)] = sha(path)
    return bundle, inputs, total, mode


def base_inputs(data: Path, inputs: dict[str, str]) -> tuple[dict[str, Any], int]:
    root = data / "normalized/plates"
    manifest = json.loads((root / "manifest.json").read_text())
    inputs[str(root / "manifest.json")] = sha(root / "manifest.json")
    codes: list[dict[str, Any]] = []
    total = 0
    for part in manifest["partitions"]:
        if part["kind"] != "plate_codes":
            continue
        path = root / part["path"].split("/normalized/plates/", 1)[1]
        digest = sha(path)
        if digest != part["sha256"]:
            raise ValueError(f"Corrupt plate input: {path}")
        inputs[str(path)] = digest
        total += part["rows"]
        for batch in pq.ParquetFile(path).iter_batches(
            batch_size=4096, columns=list(CODE_FIELDS)
        ):
            codes.extend(r for r in batch.to_pylist() if r["country_code"] in COUNTRIES)
    rules = [
        r | {"country_code": c}
        for c, items in base_policy("formats").items()
        for r in items
    ]
    rules += policy("formats") + policy("supplemental_formats")
    for rule in policy("templates"):
        rules.append(
            rule
            | {
                "pattern": template_pattern(rule["template"], rule["placeholders"]),
                "code_group": None,
            }
        )
    total += len(rules)
    formats = []
    pins = policy("sources")
    for row in rules:
        if row["country_code"] not in COUNTRIES:
            continue
        source = row["source"]
        pin = (
            base_policy("sources")[source] if pins[source].get("base") else pins[source]
        )
        formats.append(_decorate(row, source, pin))
    # Read the pinned India state table only; this utility never writes or fetches.
    for rule in policy("state_tables"):
        pin = base_policy("sources")[rule["source"]]
        path = data / "raw/plates/snapshot" / rule["source"]
        if sha(path) != pin["sha256"]:
            raise ValueError(f"Corrupt state table: {path}")
        inputs[str(path)] = sha(path)
        for cells in (
            document(pin | {"path": str(path)}).tables[rule["table"]].grid()[1:]
        ):
            codes.append(
                {
                    "country_code": rule["country_code"],
                    "code": clean_text(cells[rule["code_column"]].text),
                    "name_en": clean_text(cells[rule["name_column"]].text),
                    "name_local": None,
                    "unit_kind": "state",
                    "scope": "registration_unit",
                    "series_status": "current",
                    "subdivision_scope": None,
                    "subdivision_codes": [],
                    "source_url": pin["url"],
                    "license": pin["license"],
                }
            )
            total += 1
    return {
        "policy": policy("inference"),
        "codes": selected_codes(codes),
        "formats": formats,
        "priors": [],
    }, total
