"""Derive the writer's plate tables from verified registration and source evidence."""

from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.engines.artifact_io import file_record
from pipeline.runtime.jsonio import write_json

from . import formats, priors, tables
from .documents import Pool
from .evidence import code_rows
from .policy import Row, policy
from .sources import source_fields


def build(
    root: Path, output: Path, base: Row, pins: Pool, batch_rows: int
) -> list[Path]:
    countries = pins.get("countries.csv")
    if countries is None:
        raise ValueError("Missing pinned plate country universe: countries.csv")
    universe = priors.countries(countries)
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
    stock, rejected = priors.vehicle_rows(pins.get("vehicle-stock.json"), universe)
    grammar = list(formats.rows(pins))
    codes = code_rows(base, pins)
    inference = policy("inference")
    bundle = dict(
        policy=inference,
        countries=universe,
        priors=stock,
        formats=grammar,
        codes=codes,
    )
    bundle_path = output / "bundle.json"
    write_json(bundle_path, bundle)
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
    records = [
        tables.write(root, output, kind, rows, batch_rows)
        for kind, rows in (
            ("plate_formats", tables.formats(grammar, pins)),
            ("plate_codes", tables.codes(codes)),
            ("plate_policy", tables.policy(inference)),
            ("plate_priors", tables.priors(stock)),
        )
    ]
    report = output / "coverage.json"
    write_json(
        report,
        {
            "countries": coverage,
            "prior_rejections": rejected,
            "prior_available": bool(stock),
            "unpinned_sources": dict(sorted(pins.missing.items())),
            "counts": dict(Counter(r["status"] for r in coverage)),
        },
    )
    manifest = output / "manifest.json"
    write_json(
        manifest,
        {
            "completed": True,
            "tables": records,
            "bundle": file_record(root, bundle_path),
            "coverage": file_record(root, report),
            "sources": {
                name: source_fields(pin) for name, pin in sorted(pins.used.items())
            },
        },
    )
    return [
        *(output / f"{r['kind']}.parquet" for r in records),
        bundle_path,
        report,
        manifest,
    ]
