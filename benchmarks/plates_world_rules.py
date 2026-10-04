"""Measure every committed plate rule with local fixture geography and no priors."""

import argparse
import dataclasses
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from benchmarks.core_read_path import ROOT
from benchmarks.forward_queries import Query
from benchmarks.forward_workload import run
from pipeline.engines.plate_country.formats import _decorate
from pipeline.engines.plate_country.policy import base_policy, policy
from pipeline.engines.plate_country.syntax import template_pattern
from thereabouts import Geocoder, _core
from tools.build_sample_pack import sha
from tools.forward_sample import Subset
from tools.plate_dataset import write_tables
from tools.source_fixture import read_source


def rules() -> list[dict[str, Any]]:
    rows = [
        r | {"country_code": c}
        for c, items in base_policy("formats").items()
        for r in items
    ]
    rows += policy("formats") + policy("supplemental_formats")
    rows += [
        r
        | {
            "pattern": template_pattern(r["template"], r["placeholders"]),
            "code_group": None,
        }
        for r in policy("templates")
    ]
    pins = policy("sources")
    return [
        _decorate(
            r,
            r["source"],
            base_policy("sources")[r["source"]]
            if pins[r["source"]].get("base")
            else pins[r["source"]],
        )
        for r in rows
    ]


def build() -> tuple[Path, int]:
    root = ROOT / ".tmp/plates-world-rules"
    dataset, output = root / "dataset", root / "pack"
    rows = rules()
    if output.exists():
        return output, len(rows)
    dataset.mkdir(parents=True, exist_ok=True)
    base = ROOT / "tests/fixtures/datasets/core-synthetic/golden"
    source = Subset(base, dataset)
    bundle = read_source(ROOT / "tests/fixtures/plates-source.json.gz")["bundle"]
    bundle["formats"] = rows
    bundle["priors"] = []
    for kind in ("places", "canonical_cities", "place_to_city", "subdivisions"):
        table = source.inventory(kind)[0]
        schema = pq.read_schema(source.root / table["path"])
        source.write(kind, [], schema)
    source.write(
        "countries",
        bundle["countries"],
        pa.Table.from_pylist(bundle["countries"]).schema,
    )
    write_tables(source, bundle)
    provenance = source.finish("plates", len(rows))
    provenance["rule_files"] = {
        str(p.relative_to(ROOT)): sha(p)
        for folder in (
            "config/policies/plate_country",
            "config/policies/plates",
        )
        for p in (ROOT / folder).glob("*.yaml")
    }
    _core.write_pack(
        str(dataset),
        "plates",
        str(output),
        {
            "data_version": "synthetic",
            "core_pack": str(ROOT / "tests/fixtures/packs/core-synthetic"),
            "allow_missing_tables": ["plate_priors"],
            "input_provenance": provenance,
            "sources": ["all committed plate format policies"],
            "attribution": "Format provenance retained; see source rule files",
        },
    )
    return output, len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", choices=["before", "after", "final"], required=True)
    args = parser.parse_args()
    output, count = build()
    cases = json.loads((ROOT / "tests/fixtures/plates-vectors.json").read_text())[
        "cases"
    ]
    values = {c["request"]["values"][0] for c in cases}
    # Literal source transcriptions (escaped punctuation), not a syntax accuracy test.
    values.update(
        re.sub(r"\\([^a-zA-Z0-9])", r"\1", r["pattern"])
        for r in policy("evaluation")
        if "pattern" in r
    )
    result = run(output, "plate", [Query(v) for v in sorted(values)], 20000)
    result.update(
        {
            "rules": count,
            "countries": len({r["country_code"] for r in rules()}),
            "scope": "all committed rules; sample code assertions; no vehicle priors",
        }
    )
    with Geocoder(output) as geo:
        answers = [
            dataclasses.asdict(geo.plate(value, evidence=True))
            for value in sorted(values)
        ]
    result["semantic_sha256"] = hashlib.sha256(
        json.dumps(answers, sort_keys=True).encode()
    ).hexdigest()
    path = ROOT / "docs/measurements/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(path.read_text())
    series = data.setdefault("plates_world_rules", {})
    if args.record == "after" and "before" in series:
        assert series["before"]["semantic_sha256"] == result["semantic_sha256"]
    series[args.record] = result
    path.write_text(json.dumps(data, indent=2) + "\n")
    start, end = "<!-- plates-rules:start -->", "<!-- plates-rules:end -->"
    lines = [
        "| All-rule inference | Median / p99 (µs) | Batch rows/s |",
        "| --- | ---: | ---: |",
    ]
    for label, value in data["plates_world_rules"].items():
        lines.append(
            f"| {label} ({count} rules) | {value['scalar_median_us']:.3f} / "
            f"{value['scalar_p99_us']:.3f} | {value['batch_points_per_second']:,.0f} |"
        )
    section = start + "\n" + "\n".join(lines) + "\n" + end
    status = ROOT / "docs/CLIENT_STATUS.md"
    text = status.read_text()
    if start in text:
        text = text[: text.index(start)] + section + text[text.index(end) + len(end) :]
    else:
        text += "\n## All-rule plate inference\n\n" + section + "\n"
    status.write_text(text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
