"""Measured release statistics, licence attribution and version comparisons."""

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow.compute as pc
import pyarrow.parquet as pq

from pipeline.config import Config, policies
from pipeline.config.release import ReleaseSettings
from pipeline.engines.artifacts import read_json
from pipeline.pins.lock import read_lock
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import digest

from . import licensing
from .source import Row


def statistics(tables: list[Row]) -> Row:
    result: Row = defaultdict(lambda: {"files": 0, "rows": 0, "bytes": 0})
    for table in tables:
        item = result[table["kind"]]
        item["files"] += 1
        item["rows"] += table["rows"]
        item["bytes"] += table["size"]
    return dict(result)


# The kind whose pinned layers the reconcile policy admits by licence.
BOUNDARIES = "administrative_areas"
APACHE = "config/templates/licenses/Apache-2.0.txt"


def licences(config: Config, observed: set[str], states: set[str] | None = None) -> Row:
    """Contributing sources with the pinned files the build actually reads.

    geoBoundaries contributes country layers with a policy-compatible licence and
    the state layers of countries whose states came from it (`states`, ISO
    alpha-3; None admits every compatible state layer).
    """
    # Geographic inputs contribute decisions even when not named in an output row.
    geographic = {
        name
        for name, source in config.sources.items()
        if source.enabled
        and source.kind
        in {
            "divisions",
            BOUNDARIES,
            "places_and_names",
            "land",
            "urban_centres",
        }
    }
    used = observed | geographic
    unknown = used - config.sources.keys()
    if unknown:
        raise ValueError(f"Unknown contributing sources: {sorted(unknown)}")
    pins = read_lock(REPOSITORY / "pins.lock")
    compatible = set(
        policies.reconcile(REPOSITORY / config.engines.reconcile_policy)[
            "compatible_gb_licenses"
        ]
    )
    result = {}
    for name in sorted(used):
        pin = asdict(pins[name])
        # Evaluation evidence (plate benchmark files) is pinned but never ships.
        pin["files"] = licensing.shipped(pin["files"])
        if config.sources[name].kind == BOUNDARIES:
            pin["files"] = [
                file
                for file in pin["files"]
                if layer_used(file["metadata"].get("metadata", {}), compatible, states)
            ]
        result[name] = public({**asdict(config.sources[name].licence), "pin": pin})
    return result


def layer_used(layer: Row, compatible: set[str], states: set[str] | None) -> bool:
    """The reconcile rule (engines/reconcile/areas.py, engines/cells/inventory.py)."""
    licence = " ".join(str(layer.get("boundaryLicense") or "").split())
    if licence not in compatible:
        return False
    if layer.get("boundaryType") == "ADM0":
        return True
    return layer.get("boundaryType") == "ADM1" and (
        states is None or layer.get("boundaryISO") in states
    )


def public(value: Any) -> Any:
    """Drop mirror custody (buckets, evidence) from what a release publishes."""
    if isinstance(value, dict):
        return {
            key: public(item)
            for key, item in value.items()
            if not str(key).startswith("mirror")
        }
    if isinstance(value, list):
        return [public(item) for item in value]
    return value


def boundary_states(directory: Path, tables: list[Row]) -> set[str]:
    """ISO alpha-3 codes of countries whose state places came from geoBoundaries."""
    states: set[str] = set()
    countries: dict[str, str] = {}
    for table in tables:
        path = directory / table["path"]
        if table["kind"] == "places":
            # Filtered in Arrow: a world places table has about 6.9 M rows.
            found = pq.read_table(
                path,
                columns=["country_code"],
                filters=pc.starts_with(pc.field("place_id"), "state:geoboundaries:"),
            )
            states.update(str(code) for code in found["country_code"].to_pylist())
        elif table["kind"] == "countries":
            for row in pq.read_table(
                path, columns=["country_code", "alpha3"]
            ).to_pylist():
                if row["country_code"] and row["alpha3"]:
                    countries[row["country_code"]] = row["alpha3"]
    missing = states - countries.keys()
    if missing:
        raise ValueError(f"Countries lack alpha-3 codes: {sorted(missing)}")
    return {countries[code] for code in states}


def licence_text(sources: Row, row_licences: set[str]) -> str:
    lines = [
        "# Data licences and attribution",
        "",
        "This derived database is distributed under ODbL 1.0. "
        "Public use of a derivative database requires attribution and sharing "
        "that derivative database under ODbL. Individual source licences "
        "and notices still apply. See "
        "https://opendatacommons.org/licenses/odbl/1-0/.",
        "",
        licensing.table(sources, include_files=True),
    ]
    lines += owner_decisions(sources, row_licences)
    lines += modifications(sources, row_licences)
    lines += [
        "",
        "Licence expressions observed in exported rows: "
        + (", ".join(f"`{value}`" for value in sorted(row_licences)) or "none")
        + ". `AND` expressions retain the terms of every named input licence.",
        "",
        "Exact licence URLs, pins and provenance are shipped in "
        "`manifest.json.sources`: each source's `pin.files` records the filenames "
        "above and their per-file metadata. Source-level notices apply where "
        "file metadata does not override them. This list records inputs "
        "contributing to the exported data; geoBoundaries layers the build "
        "excludes by licence are not listed.",
    ]
    lines += apache(sources, row_licences)
    return "\n".join(lines) + "\n"


def attribution(licence: str) -> bool:
    """Creative Commons Attribution, including share-alike, in either spelling."""
    text = licence.upper()
    return "CC-BY" in text or "CC BY" in text or "COMMONS ATTRIBUTION" in text


def modifications(sources: Row, row_licences: set[str]) -> list[str]:
    """CC BY requires indicating that the licensed material was modified."""
    names = sorted(
        {
            row["source"]
            for row in licensing.rows(sources)
            if attribution(row["license"])
        }
    )
    if not names and not any(attribution(value) for value in row_licences):
        return []
    return [
        "",
        "**Modifications.** Material from "
        + (", ".join(names) or "sources named in exported rows")
        + " under Creative Commons Attribution licences was modified: records were "
        "normalized, linked to canonical places, filtered to this release, "
        "spatially indexed and re-encoded as Parquet tables and client packs. "
        "The licensors do not endorse Thereabouts or its uses.",
    ]


def apache(sources: Row, row_licences: set[str]) -> list[str]:
    """Apache-2.0 redistribution requires a copy of the licence."""
    names = sorted(
        {
            row["source"]
            for row in licensing.rows(sources)
            if "Apache-2.0" in row["license"]
        }
    )
    if not names and not any("Apache-2.0" in value for value in row_licences):
        return []
    text = (REPOSITORY / APACHE).read_text().strip("\n")
    return [
        "",
        "## Apache License 2.0",
        "",
        "Material from "
        + (", ".join(names) or "sources named in exported rows")
        + " is distributed under the Apache License, Version 2.0:",
        "",
        "```text",
        text,
        "```",
    ]


def owner_decisions(sources: Row, row_licences: set[str]) -> list[str]:
    """Share-alike content in an ODbL database is the owner's call, not ours."""
    shared = sorted(
        {
            row["source"]
            for row in licensing.rows(sources)
            if "CC-BY-SA" in row["license"]
        }
    )
    licences = sorted(
        {row["license"] for row in licensing.rows(sources)} | row_licences
    )
    share_alike = [value for value in licences if "CC-BY-SA" in value]
    if not share_alike:
        return []
    return [
        "",
        "**OWNER DECISION required before publish.** Content under "
        + ", ".join(f"`{value}`" for value in share_alike)
        + " (Wikipedia and Wikimedia pages) is included, from: "
        + (", ".join(shared) or "exported rows")
        + ". Whether share-alike content may be part of this ODbL database, and "
        "under which terms, has not been decided. Do not publish this release "
        "until the owner decides.",
    ]


def card(config: Config, stats: Row, content: Row) -> str:
    settings = config.release
    return f"""# {settings.title}

{settings.description}

Version: {settings.version}. Update frequency: {settings.update_frequency}.
Contact: {settings.contact}. Citation: {settings.citation}.

Countries: {settings.countries or "all"}.
Spatial blocks: {settings.blocks or "all"}.
Rows: {sum(t["rows"] for t in stats.values()):,}.
Parquet bytes: {sum(t["bytes"] for t in stats.values()):,}.
Files: {sum(t["files"] for t in stats.values()):,}.
Logical content SHA256: `{content["sha256"]}`.

These are geocoding labels, not legal boundary determinations. Sparse source coverage,
source conflicts, offshore locations and canonical city allocation can produce missing
or ambiguous results. Source names remain independent of city allocation.
{coverage(settings)} See README.md for exact coverage.
"""


def coverage(settings: ReleaseSettings) -> str:
    if not settings.countries and not settings.blocks:
        return "This is the complete configured world export."
    return "This spatial subset is not a complete country export."


def changes(version: str, content: Row, previous: Path | None) -> str:
    before: Row = (
        read_json(previous / "content.json")
        if previous
        else {"tables": {}, "sha256": None}
    )
    lines = [
        f"# Changes in {version}",
        "",
        f"Previous logical digest: `{before['sha256'] or 'none (first release)'}`.",
        f"Current logical digest: `{content['sha256']}`.",
        "",
        "| Table | Previous rows | Current rows | Content changed |",
        "| --- | ---: | ---: | --- |",
    ]
    for kind in sorted(before["tables"].keys() | content["tables"].keys()):
        old, new = before["tables"].get(kind, {}), content["tables"].get(kind, {})
        lines.append(
            f"| {kind} | {old.get('rows', 0)} | {new.get('rows', 0)} | "
            f"{'yes' if old.get('sha256') != new.get('sha256') else 'no'} |"
        )
    return "\n".join(lines) + "\n"


def template_identity(config: Config) -> str:
    return digest(
        {
            path: (REPOSITORY / path).read_text()
            for path in (config.release.schema, config.release.readme_template, APACHE)
        }
    )
