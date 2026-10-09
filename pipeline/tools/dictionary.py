"""Generate the data dictionary, its agent-skill references and the packaged copy.

config/dataset.yaml describes the tables, config/api.yaml the pack families and
the vocabularies the code does not enumerate, and the client and Rust core supply
the tools and result fields. `python -m pipeline dictionary` writes every output
and `--check` fails when a committed one has drifted.
"""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from pipeline.release import dataset_schema
from pipeline.runtime.fingerprints import REPOSITORY

from . import dictionary_markdown, dictionary_surface

FORMAT = "thereabouts-data-dictionary-1"
JSON_NAME = "data_dictionary.json"
MARKDOWN_NAME = "DATA_DICTIONARY.md"
HUMAN = "docs/dataset"
PACKAGED = "clients/python/thereabouts/dictionary"
SKILL = "skills/thereabouts/references"

Row = dict[str, Any]


def used_by(families: Row) -> dict[str, list[str]]:
    users: dict[str, list[str]] = {}
    for name, family in families.items():
        for table in family["tables"]:
            users.setdefault(table, []).append(name)
    return users


def table_entry(table: Row, users: list[str]) -> Row:
    columns = []
    for column in table["columns"]:
        entry = {
            key: column[key] for key in ("name", "type", "nullable", "units", "meaning")
        }
        if "values" in column:
            entry["values"] = column["values"]
        columns.append(entry)
    return {
        "description": table["description"].strip(),
        "grain": table["grain"].strip(),
        "primary_key": table["primary_key"],
        "relationships": table["relationships"],
        "columns": columns,
        "used_by": users,
    }


def vocabulary(values: list[Row]) -> list[Row]:
    return [
        {key: item[key] for key in ("value", "applies_to", "meaning")}
        for item in values
    ]


def ordered(tools: list[Row], families: Row) -> list[Row]:
    """Tools in pack-family order, each tagged with the pack it needs."""
    owner = {tool: name for name, f in families.items() for tool in f["tools"]}
    rank = {tool: index for index, tool in enumerate(owner)}
    tools = sorted(tools, key=lambda t: (rank.get(t["name"], len(rank)), t["name"]))
    return [{**tool, "pack": owner.get(tool["name"])} for tool in tools]


def build(repository: Path = REPOSITORY) -> Row:
    """The complete dictionary document for the code and schema in `repository`."""
    tables = dataset_schema.load(repository / "config/dataset.yaml", repository)
    api = yaml.safe_load((repository / "config/api.yaml").read_text())
    families = api["families"]
    users = used_by(families)
    source = repository / "core/thereabouts-core/src/result.rs"
    results = {
        **dictionary_surface.result_shape(repository),
        "status": dictionary_surface.rust_enum(source, "Status"),
        "kind": dictionary_surface.rust_enum(source, "Kind"),
        "match": dictionary_surface.rust_enum(source, "Match"),
        "evidence_reason": vocabulary(api["vocabularies"]["evidence_reason"]["values"]),
        "rank_basis": vocabulary(api["vocabularies"]["rank_basis"]["values"]),
        "errors": dictionary_surface.error_codes(),
    }
    return {
        "format": FORMAT,
        "about": " ".join(api["about"].split()),
        "packs": families,
        "tools": ordered(dictionary_surface.mcp_tools(), families),
        "resources": dictionary_surface.mcp_resources(),
        "results": results,
        "tables": {
            name: table_entry(table, users.get(name, []))
            for name, table in tables.items()
        },
    }


def render_json(document: Row) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def outputs(repository: Path = REPOSITORY) -> dict[str, str]:
    """Every generated file by repository-relative path."""
    document = build(repository)
    markdown = dictionary_markdown.render_markdown(document)
    encoded = render_json(document)
    return {
        f"{HUMAN}/{MARKDOWN_NAME}": markdown,
        f"{HUMAN}/{JSON_NAME}": encoded,
        f"{PACKAGED}/{MARKDOWN_NAME}": markdown,
        f"{PACKAGED}/{JSON_NAME}": encoded,
        f"{SKILL}/tables.md": dictionary_markdown.render_tables(document),
        f"{SKILL}/mcp-tools.md": dictionary_markdown.render_tools(document),
    }


def documents(repository: Path = REPOSITORY) -> dict[str, str]:
    """The two files a release carries, by file name, for the dataset stage."""
    generated = outputs(repository)
    return {
        MARKDOWN_NAME: generated[f"{HUMAN}/{MARKDOWN_NAME}"],
        JSON_NAME: generated[f"{HUMAN}/{JSON_NAME}"],
    }


def install(directory: Path, repository: Path = REPOSITORY) -> list[Path]:
    """Drop the dictionary into a release directory; rewriting identical bytes."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in documents(repository).items():
        path = directory / name
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    return paths


def stale(repository: Path = REPOSITORY) -> list[str]:
    """Generated files that are missing or differ from a fresh render."""
    result = []
    for relative, content in outputs(repository).items():
        path = repository / relative
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            result.append(relative)
    return result


def write(repository: Path = REPOSITORY) -> list[str]:
    changed = []
    for relative, content in outputs(repository).items():
        path = repository / relative
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        changed.append(relative)
    return changed


def main(argv: Sequence[str], repository: Path = REPOSITORY) -> int:
    parser = argparse.ArgumentParser(prog="pipeline dictionary", description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if a committed file is stale"
    )
    args = parser.parse_args(argv)
    if args.check:
        drifted = stale(repository)
        for relative in drifted:
            print(f"stale: {relative}")
        if drifted:
            print("run `python -m pipeline dictionary` and commit the result")
        return int(bool(drifted))
    for relative in write(repository):
        print(f"wrote {relative}")
    return 0
