"""Bounded, checkpointed text normalization and common manifest publication."""

import json
import time
from collections import Counter, defaultdict
from itertools import islice
from pathlib import Path
from typing import Any

import h3

from .artifacts import publish_report, read_json
from .io import fingerprint, write_json
from .ledger import Ledger
from .lifecycle import finish_source, resume_source
from .lookup_codes import country, geonames_countries, subdivision
from .lookup_phone import metadata, prefix, territories
from .lookup_points import airport, ip_range, postal, trade
from .lookup_reader import records
from .lookup_rows import Reject, Row, decorate
from .lookup_schemas import LOOKUP_SCHEMAS, LookupKind
from .runtime import resources, single_run
from .schemas import SCHEMA_HASHES
from .workspace import Workspace
from .writer import PartitionWriter

CHUNK_ROWS = 10000


def configuration() -> Row:
    return dict(
        builder="extra-lookups-1",
        h3_version=h3.__version__,
        resolution=8,
        schemas={k: SCHEMA_HASHES[k] for k in LOOKUP_SCHEMAS},
        chunk_rows=CHUNK_ROWS,
    )


def convert(kind: LookupKind, name: str, raw: Row, reference: Row) -> Row:
    if kind == "postal_codes":
        return postal(raw["fields"], name)
    if kind == "airports":
        return airport(raw)
    if kind == "trade_locations":
        return trade(raw)
    if kind == "ip_ranges":
        return ip_range(raw["fields"])
    if kind == "countries":
        return country(raw, reference)
    if kind == "subdivisions":
        return subdivision(raw, name)
    if kind == "phone_metadata":
        return metadata(raw)
    if kind == "phone_prefixes":
        return prefix(raw, name, reference)
    raise ValueError(f"Unexpected text kind: {kind}")


def normalize_unit(
    workspace: Workspace,
    source: str,
    name: str,
    ordinal: int,
    rows: list[tuple[LookupKind, Row]],
    inventory: Row,
    reference: Row,
) -> tuple[Row, Row]:
    unit = f"{name}#{ordinal:06d}"
    pin = dict(inventory["files"][name])
    digest = fingerprint(dict(inventory=inventory, config=configuration(), unit=unit))
    report_path = workspace.normalized(source) / "audits" / digest / "report.json"
    ledger = Ledger(workspace.ledger_path)
    commit = dict(stage=f"{source}.normalize", unit_id=unit, inputs_hash=digest)
    if ledger.is_complete(**commit):
        return commit, read_json(report_path)
    writers: dict[LookupKind, PartitionWriter] = {}
    counts: Counter[str] = Counter()
    rejects: list[Row] = []
    families: Counter[str] = Counter()
    if source == "codes" and name == "country-codes.csv":
        pin["license"] = "PDDL-1.0 AND CC-BY-4.0"
        pin["attribution"] += "; GeoNames countryInfo (CC-BY-4.0)"
    for index, (kind, raw) in enumerate(rows):
        number = ordinal * CHUNK_ROWS + index + 1
        try:
            row = convert(kind, name, raw, reference)
        except Reject as error:
            rejects.append(dict(record=number, reason=str(error), raw=raw))
            continue
        counts["invalid_coordinates"] += int(bool(row.get("coordinate_error")))
        if "h3" in row:
            counts["located"] += int(row["h3"] is not None)
            counts["unlocated"] += int(row["h3"] is None)
        if kind == "ip_ranges":
            families[str(row["ip_version"])] += 1
        evidence = (
            raw
            if kind != "countries"
            else {**raw, "geonames_countryInfo": reference.get(row["country_code"])}
        )
        row = decorate(
            row, source, f"{name}:{number}", pin, inventory["source_release"], evidence
        )
        if kind not in writers:
            writers[kind] = PartitionWriter(workspace, source, kind, unit, digest)
        writers[kind].add(row)
    outputs = [path for writer in writers.values() for path in writer.finish()]
    report = dict(
        input_rows=len(rows),
        output_rows={k: w.count for k, w in writers.items()},
        rejects=len(rejects),
        **counts,
        ip_versions=dict(families),
    )
    if rejects:
        reject_path = report_path.with_name("rejects.json")
        write_json(reject_path, {"records": rejects})
        outputs.append(reject_path)
    write_json(report_path, report)
    ledger.complete(**commit, outputs=[*outputs, report_path], metadata=report)
    print(f"NORMALIZE {source}/{unit}: {report['output_rows']}", flush=True)
    return commit, report


def normalize(workspace: Workspace, source: str) -> None:
    with single_run(workspace, source):
        if resume_source(workspace, source, configuration()):
            return
        started = time.monotonic()
        inventory = read_json(workspace.raw(source) / "inventory.json")
        if "completed_at" not in inventory:
            raise ValueError("Download is incomplete")
        ledger = Ledger(workspace.ledger_path)
        for name, pin in inventory["files"].items():
            if not ledger.is_complete(f"{source}.download", name, fingerprint(pin)):
                raise ValueError(f"Unverified input: {name}")
        reference: Row = {}
        if source == "codes":
            reference = geonames_countries(
                Path(inventory["files"]["countryInfo.txt"]["path"])
            )
        elif source == "phone":
            reference = defaultdict(list)
            for row in territories(
                Path(inventory["files"]["resources/PhoneNumberMetadata.xml"]["path"])
            ):
                reference[row["countryCode"]].append(row["id"])
        commits: list[Row] = []
        counts: Counter[str] = Counter()
        outputs: Counter[str] = Counter()
        families: Counter[str] = Counter()
        file_counts: dict[str, Any] = {}
        for name, pin in inventory["files"].items():
            iterator = records(source, name, pin, inventory)
            ordinal = 0
            file_rows = 0
            while rows := list(islice(iterator, CHUNK_ROWS)):
                commit, report = normalize_unit(
                    workspace, source, name, ordinal, rows, inventory, reference
                )
                commits.append(commit)
                for key in (
                    "input_rows",
                    "rejects",
                    "located",
                    "unlocated",
                    "invalid_coordinates",
                ):
                    counts[key] += report.get(key, 0)
                outputs.update(report["output_rows"])
                families.update(report["ip_versions"])
                file_rows += report["input_rows"]
                ordinal += 1
            if file_rows:
                file_counts[name] = file_rows
        if (
            source == "dbip"
            and counts["input_rows"]
            != inventory["files"]["dbip-city-lite-2026-10.csv.gz"]["publisher_rows"]
        ):
            raise ValueError("DB-IP row count disagrees with publisher")
        report = dict(
            counts,
            output_rows=dict(outputs),
            files=file_counts,
            ip_versions=dict(families),
            **resources(started),
        )
        summary = publish_report(workspace, source, report)
        licenses = (
            workspace.normalized(source) / f"licenses-{fingerprint(inventory)}.json"
        )
        write_json(
            licenses,
            {
                name: {
                    key: pin[key]
                    for key in ("url", "license", "license_url", "attribution")
                }
                for name, pin in inventory["files"].items()
            },
        )
        finish_source(
            workspace,
            source,
            inventory["source_release"],
            commits,
            [summary, licenses],
            configuration(),
        )
        print(json.dumps(report), flush=True)
