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
    template: Path,
) -> str:
    settings = config.release
    tree, sections = [], []
    for kind, counts in stats.items():
        layout = (
            f"{kind}/group=*/part.parquet"
            if kind == "cells"
            else f"{kind}/country=*/part.parquet"
            if kind in {"places", "canonical_cities", "place_to_city"}
            else f"{kind}/part.parquet"
        )
        tree.append(
            f"├── {layout}  # {counts['rows']:,} rows; {counts['bytes']:,} bytes"
        )
        schema = descriptions[kind]
        keys = ", ".join(schema["primary_key"]) or "none; observations can repeat"
        sections += [
            f"### `{kind}`",
            "",
            f"Layout: `{layout}`. Primary key: {keys}. "
            f"{counts['files']:,} files, {counts['rows']:,} rows, "
            f"{counts['bytes']:,} compressed bytes.",
            "",
            "| Column | Arrow type | Nullable | Units | Meaning |",
            "| --- | --- | --- | --- | --- |",
        ]
        for column in schema["columns"]:
            sections.append(
                f"| `{column['name']}` | `{column['type']}` | "
                f"{'yes' if column['nullable'] else 'no'} | "
                f"{column['units']} | {column['meaning']} |"
            )
        sections.append("")
    for name, meaning in [
        ("manifest.json", "file checksums, rows, schema, pins and policy"),
        ("content.json", "partition-independent logical table digests"),
        ("DATA_LICENSES.md", "licences and attribution for contributing sources"),
        ("DATASET_CARD.md", "purpose, coverage and measured statistics"),
        ("CHANGES.md", "comparison with the previous logical digest"),
        ("README.md", "this guide"),
    ]:
        tree.append(f"├── {name}  # {meaning}")
    tree[-1] = tree[-1].replace("├", "└", 1)
    coverage = (
        "This is the complete configured world export."
        if not settings.countries and not settings.blocks
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
        "tree": "\n".join(tree),
        "tables": "\n".join(sections),
        "licences": table(sources, include_files=False),
        "group_resolution": str(settings.dataset.cell_group_resolution),
        "blocks_per_group": str(
            7 ** (config.h3.block_resolution - settings.dataset.cell_group_resolution)
        ),
        "distant_m": str(policy["distant_m"]),
        "nearest_m": str(policy["nearest_m"]),
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
