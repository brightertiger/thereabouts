"""Render the public dataset documentation from verified schemas and statistics."""

from pathlib import Path

from pipeline.config import Config

from .licensing import table
from .source import Row


def render(
    config: Config,
    stats: Row,
    descriptions: Row,
    sources: Row,
    policy: Row,
    recorded: Row,
    template: Path,
) -> str:
    """`recorded` holds the manifest's `quality_gates` and `closure`, or neither
    for the committed page rendered from older measurements."""
    settings = config.release
    tree, sections = [], []
    for kind, schema in descriptions.items():
        layout = (
            f"{kind}/group=*/part.parquet"
            if kind == "cells"
            else f"{kind}/country=*/part.parquet"
            if kind in {"places", "canonical_cities", "place_to_city"}
            else f"{kind}/part.parquet"
        )
        counts = stats.get(kind)
        measured = (
            f"{counts['files']:,} files, {counts['rows']:,} rows, "
            f"{counts['bytes']:,} compressed bytes."
            if counts
            else "Not measured in this export."
        )
        tree.append(
            f"├── {layout}  # {counts['rows']:,} rows; {counts['bytes']:,} bytes"
            if counts
            else f"├── {layout}  # not measured in this export"
        )
        keys = ", ".join(schema["primary_key"]) or "none"
        sections += [
            f"### `{kind}`",
            "",
            f"Layout: `{layout}`. Primary key: {keys}. {measured}",
            "",
            "| Column | Arrow type | Nullable | Units | Meaning |",
            "| --- | --- | --- | --- | --- |",
        ]
        for column in schema["columns"]:
            nullable = "yes" if column["nullable"] else "no"
            if column["nullable"] and column["name"] in schema["primary_key"]:
                nullable = "yes in Arrow; no for the logical key"
            sections.append(
                f"| `{column['name']}` | `{column['type']}` | "
                f"{nullable} | "
                f"{column['units']} | {column['meaning']} |"
            )
        sections.append("")
    for name, meaning in [
        ("manifest.json", "file checksums, rows, schema, pins and policy"),
        ("content.json", "partition-independent logical table digests"),
        ("DATA_DICTIONARY.md", "tables, keys, relationships and coded values"),
        ("data_dictionary.json", "the same dictionary, with the MCP tools, as JSON"),
        ("DATA_LICENSES.md", "licences and attribution for contributing sources"),
        ("DATASET_CARD.md", "purpose, coverage and measured statistics"),
        ("CHANGES.md", "comparison with the previous logical digest"),
        ("README.md", "this guide"),
    ]:
        tree.append(f"├── {name}  # {meaning}")
    tree[-1] = tree[-1].replace("├", "└", 1)
    world = not settings.countries and not settings.blocks
    coverage = (
        "This is the complete configured world export."
        if world
        else (
            f"This subset contains country catalogues for "
            f"{', '.join(settings.countries) or 'all countries'} "
            f"and spatial coverage in H3 blocks {', '.join(settings.blocks)}. "
            "Located observations are filtered to these blocks; "
            "unlocated observations for selected countries are retained."
        )
    )
    values = {
        "version": settings.version,
        "coverage": coverage,
        "scope": "export" if world else "subset",
        "remote": remote(public_base(config), settings.version),
        "tree": "\n".join(tree),
        "tables": "\n".join(sections),
        "licences": table(sources, include_files=False),
        "group_resolution": str(settings.dataset.cell_group_resolution),
        "blocks_per_group": str(
            7 ** (config.h3.block_resolution - settings.dataset.cell_group_resolution)
        ),
        "distant_m": str(policy["distant_m"]),
        "nearest_m": str(policy["nearest_m"]),
        "quality_gates": quality(recorded.get("quality_gates")),
        "closure": closure(recorded.get("closure")),
        "latitude": str(settings.example_latitude),
        "longitude": str(settings.example_longitude),
        "contact": settings.contact,
        "citation": settings.citation,
        "documentation": settings.documentation,
    }
    value = template.read_text()
    for key, replacement in values.items():
        value = value.replace("{{" + key + "}}", replacement)
    if "{{" in value:
        raise ValueError("Unresolved README template placeholder")
    return value


def quality(gates: Row | None) -> str:
    """The lookups quality gates this export passed, and its advisory totals.

    Assembly always passes gates; None renders the committed documentation from
    measurements recorded before the gates existed."""
    if gates is None:
        return (
            "The measured export this page was rendered from predates these gates. "
            "A release's `manifest.json.quality_gates` records its blocking scope, "
            "its reviewed countries and its advisory totals."
        )
    stop = (
        "A boundary loss without a reviewed exception, or a city footprint "
        "failure, stops the build"
    )
    if gates["blocking_scope"] == "all":
        return (
            f"Blocking scope: `all`. {stop} in every country, as do integrity, "
            "reference, neighbour and named-point failures. This export has none, "
            "so it has no advisory findings. `manifest.json.quality_gates` records "
            "the scope."
        )
    reviewed = gates["reviewed_countries"]
    advisory = gates["advisory"]
    plural = {
        "boundary_losses": "" if advisory["boundary_losses"] == 1 else "es",
        "footprint_failures": "" if advisory["footprint_failures"] == 1 else "s",
        "countries": "y" if advisory["countries"] == 1 else "ies",
    }
    return (
        f"Blocking scope: `reviewed`. {stop} in the {len(reviewed)} reviewed "
        f"countries ({', '.join(reviewed)}); integrity, reference, neighbour and "
        "named-point failures stop it in every country. This export has none. In "
        "the other countries boundary losses and footprint failures are advisory: "
        "measured, counted and kept, but not blocking. This export has "
        f"{advisory['boundary_losses']:,} advisory boundary "
        f"loss{plural['boundary_losses']} ({advisory['lost_cells']:,} cells) and "
        f"{advisory['footprint_failures']:,} footprint "
        f"failure{plural['footprint_failures']} in {advisory['countries']:,} "
        f"unreviewed countr{plural['countries']}.\n\n"
        "`manifest.json.quality_gates` holds the scope, the reviewed countries and "
        "these totals. Every finding, with per-country counts, is listed in the "
        "pipeline's `quality.json` under `advisory_spatial_gates` and "
        "`gate_scope.by_country`. That file is not part of this directory; "
        "`quality_gates.report` gives its pipeline path, byte size and SHA256."
    )


def closure(record: Row | None) -> str:
    """The references assembly rewrote or dropped, from the manifest's record.

    None renders the committed documentation from measurements recorded before
    assembly kept the record."""
    if record is None:
        return (
            "The measured export this page was rendered from predates this record. "
            "A release's `manifest.json.closure` lists every reference that assembly "
            "rewrote or dropped."
        )
    aliased, excluded = record["aliased"], record["excluded"]
    if not aliased and not excluded:
        return (
            "This export needed neither: `manifest.json.closure` lists no alias and "
            "no exclusion."
        )
    rewritten = sum(entry["rows"] for entry in aliased)
    dropped = sum(entry["rows"] for entry in excluded)
    rows = []
    for entry in [*aliased, *excluded]:
        published = f"`{entry['to']}`" if "to" in entry else "row dropped"
        rows.append(
            f"| `{entry['table']}` | `{entry['column']}` | `{entry['place']}` | "
            f"{published} | {entry['rows']:,} |"
        )
    return "\n".join(
        [
            f"This export rewrote {rewritten:,} row{'' if rewritten == 1 else 's'} "
            f"and dropped {dropped:,} row{'' if dropped == 1 else 's'}:",
            "",
            "| Table | Column | Missing key | Published as | Rows |",
            "| --- | --- | --- | --- | --- |",
            *rows,
        ]
    )


def public_base(config: Config) -> str:
    """The publication destination, when it is a public object-store URL."""
    destination = config.storage.get("s3_release", "").rstrip("/")
    return destination if destination.startswith("s3://") else ""


def remote(base: str, version: str) -> str:
    if not base:
        return (
            "A published copy is read the same way: replace the local directory in "
            "the first and fourth SQL parameters with the published "
            f"`dataset/{version}/` location. DuckDB needs its `httpfs` extension "
            "for remote paths."
        )
    return (
        f"For S3, use `{base}/dataset/{version}/cells/**/*.parquet` and "
        f"`{base}/dataset/{version}/places/**/*.parquet` for the first and fourth "
        "SQL parameters. DuckDB needs its `httpfs` extension and the bucket's "
        "region and credentials, or public anonymous access."
    )
