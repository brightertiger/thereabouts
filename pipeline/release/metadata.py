"""Measured release statistics, licence attribution and version comparisons."""

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from pipeline.config import Config
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


def licences(config: Config, observed: set[str]) -> Row:
    # Geographic inputs contribute decisions even when not named in an output row.
    geographic = {
        name
        for name, source in config.sources.items()
        if source.enabled
        and source.kind
        in {
            "divisions",
            "administrative_areas",
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
    return {
        name: {**asdict(config.sources[name].licence), "pin": asdict(pins[name])}
        for name in sorted(used)
    }


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
        "contributing to the exported data.",
    ]
    return "\n".join(lines) + "\n"


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
            for path in (config.release.schema, config.release.readme_template)
        }
    )
