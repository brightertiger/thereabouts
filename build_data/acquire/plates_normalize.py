"""Offline plate extraction, bounded publication and coverage accounting."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .artifacts import publish_report, read_json
from .io import fingerprint, sha256_file, write_json
from .ledger import Ledger
from .lifecycle import finish_source, resume_source
from .lookup_rows import decorate
from .plates_config import DATA, configuration, policy
from .plates_coverage import reviewed_scopes
from .plates_reader import records
from .plates_schemas import PlateKind
from .runtime import single_run
from .workspace import Workspace
from .writer import PartitionWriter

Row = dict[str, Any]


def normalize(workspace: Workspace) -> None:
    """Only cached bytes are read; missing pins or unmatched rules fail closed."""
    with single_run(workspace, "plates"):
        config = configuration()
        if resume_source(workspace, "plates", config):
            return
        inventory = read_json(workspace.raw("plates") / "inventory.json")
        if not inventory.get("completed_at"):
            raise ValueError("Complete the plates download stage first")
        if inventory["specifications"] != policy("sources"):
            raise ValueError("Source catalog changed; run plates download first")
        for name, pin in inventory["files"].items():
            if sha256_file(Path(pin["path"])) != pin["sha256"]:
                raise ValueError(f"Corrupt raw snapshot: {name}")
        ledger = Ledger(workspace.ledger_path)
        digest = fingerprint(dict(inventory=inventory, configuration=config))
        unit = dict(stage="plates.normalize", unit_id="evidence", inputs_hash=digest)
        writers: dict[PlateKind, PartitionWriter] = {}
        rows: Counter[str] = Counter()
        classes: Counter[str] = Counter()
        country_rows: Counter[str] = Counter()
        current: dict[str, set[str]] = defaultdict(set)
        distinct: dict[str, set[str]] = defaultdict(set)
        source_codes: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        current_sources: dict[str, dict[str, set[str]]] = defaultdict(
            lambda: defaultdict(set)
        )
        identifiers: Counter[str] = Counter()
        formats: Counter[str] = Counter()
        examples: Counter[str] = Counter()
        rejections: list[Row] = []
        for kind, row, source in records(inventory, rejections):
            pin = inventory["files"][source]
            raw = dict(row)
            raw["snapshot"] = dict(file=source, sha256=pin["sha256"])
            row.update(source_url=pin["url"], retrieved_at=pin["retrieved_at"])
            decorated = decorate(
                row,
                "plates",
                f"{source}#{kind}#{fingerprint(raw)}",
                pin,
                inventory["source_release"],
                raw,
            )
            if kind not in writers:
                writers[kind] = PartitionWriter(workspace, "plates", kind, kind, digest)
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
            reviewed_scopes=reviewed_scopes(source_codes, current_sources),
            per_source_codes={
                cc: {source: len(codes) for source, codes in data.items()}
                for cc, data in source_codes.items()
            },
            rejected_assertions=rejections,
        )
        summary = publish_report(workspace, "plates", report)
        licenses = workspace.normalized("plates") / f"licenses-{digest}.json"
        write_json(
            licenses,
            {
                name: {
                    key: pin[key]
                    for key in (
                        "url",
                        "license",
                        "license_url",
                        "attribution",
                        "retrieved_at",
                        "sha256",
                    )
                }
                for name, pin in inventory["files"].items()
            },
        )
        ledger.complete(
            **unit, outputs=[*outputs, summary], metadata=dict(output_rows=dict(rows))
        )
        finish_source(
            workspace,
            "plates",
            inventory["source_release"],
            [unit],
            [summary, licenses, *sorted(DATA.glob("*.json"))],
            config,
        )
        print(json.dumps(dict(output_rows=dict(rows), report=str(summary))), flush=True)


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
