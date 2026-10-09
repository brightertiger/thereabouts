"""Offline plate extraction, bounded publication and coverage accounting."""

import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pipeline.runtime.jsonio import digest, write_json
from pipeline.sources.contract import SourceContext
from pipeline.sources.policy import read_policies
from pipeline.sources.shared.lookup_rows import decorate
from pipeline.sources.shared.manifest import finish
from pipeline.sources.shared.plates_schemas import PlateKind
from pipeline.sources.shared.writer import PartitionWriter

from . import documents
from .coverage import reviewed_scopes
from .reader import records

Row = dict[str, Any]


def normalize(ctx: SourceContext) -> list[Path]:
    """Only cached bytes are read; missing pins or unmatched rules fail closed."""
    policies = read_policies(ctx.settings)
    if any(pin.metadata.get("kind") == "pdf" for pin in ctx.pin.files):
        version = subprocess.run(
            ["pdftotext", "-v"], check=True, capture_output=True, text=True
        )
        actual = (version.stderr or version.stdout).splitlines()[0]
        if actual != ctx.settings.options["pdf_version"]:
            raise ValueError(f"PDF decoder differs from configured version: {actual}")
    for pin in ctx.pin.files:
        if pin.size > int(ctx.settings.options["document_bytes"]):
            raise ValueError(f"Plate evidence exceeds document_bytes: {pin.name}")
    inventory: Row = {
        "source_release": ctx.pin.release,
        "files": {
            str(pin.metadata.get("key", pin.name)): {
                "license": ctx.settings.licence.id,
                "license_url": ctx.settings.licence.url,
                "attribution": ctx.settings.licence.attribution,
                "retrieved_at": ctx.pin.pinned_at,
                **pin.metadata,
                "url": pin.url,
                "sha256": pin.sha256,
                "path": str(ctx.input(pin.name)),
            }
            for pin in ctx.pin.files
        },
    }
    writers: dict[PlateKind, PartitionWriter] = {}
    rows: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    country_rows: Counter[str] = Counter()
    current: dict[str, set[str]] = defaultdict(set)
    distinct: dict[str, set[str]] = defaultdict(set)
    source_codes: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    current_sources: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    identifiers: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    examples: Counter[str] = Counter()
    rejections: list[Row] = []
    for kind, row, source in records(
        inventory, policies, int(ctx.settings.options["example_limit"]), rejections
    ):
        pin = inventory["files"][source]
        raw = dict(row)
        raw["snapshot"] = dict(file=source, sha256=pin["sha256"])
        row.update(source_url=pin["url"], retrieved_at=pin["retrieved_at"])
        decorated = decorate(
            row,
            "plates",
            f"{source}#{kind}#{digest(raw)}",
            pin,
            inventory["source_release"],
            raw,
        )
        if kind not in writers:
            writers[kind] = PartitionWriter(ctx, kind, kind)
        writers[kind].add(decorated)
        rows[kind] += 1
        country = row["country_code"]
        if kind == "plate_codes":
            country_rows[country] += 1
            distinct[country].add(row["code"])
            source_codes[country][source].add(row["code"])
            if row["series_status"] == "current":
                current[country].add(row["code"])
                current_sources[country][source].add(row["code"])
            identifiers["wikidata"] += bool(row.get("wikidata_id"))
            identifiers["coordinates"] += row.get("latitude") is not None
        elif kind == "plate_survey":
            classes[row["classification"]] += 1
        else:
            formats[country] += 1
            examples[country] += len(row["examples"])
    outputs = [p for writer in writers.values() for p in writer.finish()]
    outputs.append(documents.write(ctx, inventory["files"]))
    report = dict(
        output_rows=dict(rows),
        survey_classes=dict(classes),
        coverage={
            cc: dict(
                rows=country_rows[cc],
                distinct_codes=len(distinct[cc]),
                current_codes=len(current[cc]),
                formats=formats[cc],
                examples=examples[cc],
                completeness="not_established",
            )
            for cc in sorted(set(country_rows) | set(formats))
        },
        identifiers=dict(identifiers),
        distinct_country_codes=sum(map(len, distinct.values())),
        distinct_code_strings=len(set().union(*distinct.values())),
        cross_checks=_comparisons(source_codes),
        current_series_cross_checks=_comparisons(current_sources),
        reviewed_scopes=reviewed_scopes(
            source_codes, current_sources, policies["coverage"]
        ),
        per_source_codes={
            cc: {source: len(codes) for source, codes in data.items()}
            for cc, data in source_codes.items()
        },
        rejected_assertions=rejections,
    )
    summary = ctx.normalized / "audits" / ctx.unit.inputs_hash / "report.json"
    write_json(ctx.ensure(summary), report)
    return finish(ctx, outputs, [summary])


def _comparisons(sources: dict[str, dict[str, set[str]]]) -> list[Row]:
    """Code-set differences are evidence gaps, not automatic semantic conflicts."""
    comparisons: list[Row] = []
    for country, data in sorted(sources.items()):
        names = sorted(data)
        for i, left in enumerate(names):
            for right in names[i + 1 :]:
                a, b = data[left], data[right]
                comparisons.append(
                    dict(
                        country_code=country,
                        left=left,
                        right=right,
                        intersection=len(a & b),
                        only_left=sorted(a - b),
                        only_right=sorted(b - a),
                        interpretation=(
                            "Unadjudicated set differences; validity periods "
                            "and entity scopes may differ"
                        ),
                    )
                )
    return comparisons
