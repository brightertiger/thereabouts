"""Rebuild inference artifacts from verified acquisition outputs and pinned bytes."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from build_data.acquire.io import sha256_file, write_json
from build_data.acquire.manifests import load_manifest
from build_data.acquire.plates_html import clean_text
from build_data.acquire.plates_reader import document
from build_data.acquire.workspace import Workspace

from . import formats, priors
from .policy import DATA, Row, policy
from .sources import pins, source_fields


def code_rows(manifest: Row, sources: dict[str, Row]) -> list[Row]:
    keep = (
        "country_code",
        "code",
        "name_en",
        "name_local",
        "unit_kind",
        "scope",
        "series_status",
        "series_id",
        "subdivision_scope",
        "source_url",
        "license",
        "wikidata_id",
        "subdivision_codes",
        "geonames_ids",
        "latitude",
        "longitude",
    )
    result = []
    for part in manifest["partitions"]:
        if part["kind"] != "plate_codes":
            continue
        for raw in pq.read_table(part["path"]).to_pylist():
            result.append({k: raw[k] for k in keep})
    for rule in policy("state_tables"):
        pin = sources[rule["source"]]
        for cells in document(pin).tables[rule["table"]].grid()[1:]:
            result.append(
                dict(
                    country_code=rule["country_code"],
                    code=clean_text(cells[rule["code_column"]].text),
                    name_en=clean_text(cells[rule["name_column"]].text),
                    name_local=None,
                    unit_kind="state",
                    scope="registration_unit",
                    series_status="current",
                    series_id="state-prefix",
                    subdivision_scope=None,
                    source_url=pin["url"],
                    license=pin["license"],
                )
            )
    return result


def build(data: Path, *, offline: bool = True) -> Row:
    source_pins = pins(data, offline=offline)
    base = load_manifest(Workspace(data.resolve()), "plates")
    universe = priors.countries(source_pins["countries.csv"])
    # The accepted source has the separately evidenced Kosovo row.
    for part in base["partitions"]:
        if part["kind"] == "plate_survey":
            known = {r["country_code"] for r in universe}
            universe.extend(
                dict(
                    country_code=r["country_code"],
                    name=r["name"],
                    region=policy("extra_regions")[r["country_code"]],
                    aliases=[],
                )
                for r in pq.read_table(part["path"]).to_pylist()
                if r["country_code"] not in known
            )
    stock, rejected = priors.vehicle_rows(source_pins["vehicle-stock.json"], universe)
    grammar = list(formats.rows(source_pins))
    codes = code_rows(base, source_pins)
    bundle = dict(
        version=1,
        policy=policy("inference"),
        countries=universe,
        priors=stock,
        formats=grammar,
        codes=codes,
    )
    output = data / "normalized" / "plates_country"
    output.mkdir(parents=True, exist_ok=True)
    # All policy/report inputs enter the release key: a gap-note edit must not
    # overwrite a previously published coverage artifact under the same name.
    config = configuration()
    base_hash = sha256_file(data / "normalized" / "plates" / "manifest.json")
    release_inputs = dict(
        bundle=bundle,
        configuration=config,
        base_manifest=base_hash,
        prior_rejections=rejected,
    )
    encoded = json.dumps(release_inputs, ensure_ascii=False, sort_keys=True).encode()
    release = hashlib.sha256(encoded).hexdigest()
    bundle_name = f"bundle-{release}.json"
    write_json(output / bundle_name, bundle)
    coverage = [
        dict(
            country_code=r["country_code"],
            name=r["name"],
            region=r["region"],
            rules=sum(f["country_code"] == r["country_code"] for f in grammar),
            status="partial_syntax"
            if any(f["country_code"] == r["country_code"] for f in grammar)
            else "gap",
            gap=policy("gaps").get(
                r["country_code"],
                "Special, vanity and some historical series "
                "are not exhaustively modeled.",
            ),
        )
        for r in universe
    ]
    tables = {"formats": grammar, "vehicle_priors": stock, "coverage": coverage}
    names = [bundle_name]
    for kind, rows in tables.items():
        # Evidence JSON is portable without coupling clients to nested Arrow types.
        records = [
            dict(
                country_code=r["country_code"],
                evidence_json=json.dumps(r, ensure_ascii=False, sort_keys=True),
            )
            for r in rows
        ]
        schema = pa.schema(
            [
                pa.field("country_code", pa.string(), nullable=False),
                pa.field("evidence_json", pa.string(), nullable=False),
            ],
            metadata={b"schema_version": b"plates-country-1", b"kind": kind.encode()},
        )
        name = f"{kind}-{release}.parquet"
        pq.write_table(pa.Table.from_pylist(records, schema=schema), output / name)
        names.append(name)
    report_name = f"coverage-{release}.json"
    write_json(
        output / report_name,
        dict(
            countries=coverage,
            prior_rejections=rejected,
            counts=dict(Counter(r["status"] for r in coverage)),
        ),
    )
    names.append(report_name)
    manifest: dict[str, Any] = dict(
        version=1,
        release=release,
        bundle=bundle_name,
        coverage=report_name,
        base_manifest_sha256=base_hash,
        **config,
        sources={name: source_fields(pin) for name, pin in source_pins.items()},
        outputs=[dict(file=name, sha256=sha256_file(output / name)) for name in names],
        counts=dict(
            formats=len(grammar),
            countries=len({r["country_code"] for r in grammar}),
            priors=len(stock),
        ),
    )
    write_json(output / "manifest.json", manifest)
    return manifest


def verify(data: Path) -> None:
    """Verify the policy/base snapshot as well as raw and normalized hashes."""
    from build_data.acquire.artifacts import read_json

    manifest = read_json(data / "normalized" / "plates_country" / "manifest.json")
    pins(data)
    for key, expected in configuration().items():
        if expected != manifest.get(key):
            raise ValueError(f"Resolver {key} changed; rebuild before reporting status")
    if (
        sha256_file(data / "normalized" / "plates" / "manifest.json")
        != manifest["base_manifest_sha256"]
    ):
        raise ValueError("Base plates release changed; rebuild")
    load_manifest(Workspace(data.resolve()), "plates")


def configuration() -> Row:
    """Inputs outside the bundle that still affect release behavior and reports."""
    return dict(
        policies={p.name: sha256_file(p) for p in DATA.glob("*.json")},
        implementation={
            p.name: sha256_file(p) for p in Path(__file__).parent.glob("*.py")
        },
    )
