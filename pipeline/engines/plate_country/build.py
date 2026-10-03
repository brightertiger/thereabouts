"""Derive inference tables from verified registration and raw source evidence."""

from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.engines.artifact_io import file_record, parquet
from pipeline.engines.reconcile.common import encode
from pipeline.runtime.jsonio import write_json

from . import formats, priors
from .evidence import code_rows
from .policy import Row, policy
from .sources import source_fields


def build(
    root: Path, output: Path, base: Row, sources: dict[str, Row], batch_rows: int
) -> list[Path]:
    universe = priors.countries(sources["countries.csv"])
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
    stock, rejected = priors.vehicle_rows(sources["vehicle-stock.json"], universe)
    grammar = list(formats.rows(sources))
    codes = code_rows(base, sources)
    bundle = dict(
        policy=policy("inference"),
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
    records, outputs = [], [bundle_path]
    schema = pa.schema(
        [
            pa.field("country_code", pa.string(), nullable=False),
            pa.field("evidence_json", pa.string(), nullable=False),
        ]
    )
    for kind, rows in {
        "formats": grammar,
        "vehicle_priors": stock,
        "coverage": coverage,
    }.items():
        path = output / f"{kind}.parquet"
        record = parquet(
            root,
            path,
            (
                {"country_code": r["country_code"], "evidence_json": encode(r)}
                for r in rows
            ),
            schema,
            batch_rows,
        )
        records.append({**record, "kind": "plate_country_" + kind})
        outputs.append(path)
    report = output / "coverage.json"
    write_json(
        report,
        {
            "countries": coverage,
            "prior_rejections": rejected,
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
            "sources": {name: source_fields(pin) for name, pin in sources.items()},
        },
    )
    return [*outputs, report, manifest]
