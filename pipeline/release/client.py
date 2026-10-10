"""The sole bridge to the client-owned pack writer; no binary format code lives here."""

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.paths import located

from .dictionary import JSON_NAME, MARKDOWN_NAME
from .source import Row
from .verify import verify_dataset

Writer = Callable[[str, str, str, dict[str, Any]], dict[str, Any]]


def binding() -> Writer:
    try:
        core = importlib.import_module("thereabouts._core")
        writer = core.write_pack
    except (ImportError, AttributeError) as error:
        raise ValueError(
            "Pack writing requires the merged Rust client "
            "and thereabouts._core.write_pack"
        ) from error
    return cast(Writer, writer)


def write(
    dataset: Path, family: str, output: Path, version: str, writer: Writer
) -> list[Path]:
    manifest = verify_dataset(dataset)
    notices = {"DATA_LICENSES.md": (dataset / "DATA_LICENSES.md").read_text()}
    if family == "core":
        # The MCP server reads the installed core pack's dictionary first.
        listed = {record["path"] for record in manifest["files"]}
        notices |= {
            name: (dataset / name).read_text()
            for name in (MARKDOWN_NAME, JSON_NAME)
            if name in listed
        }
    options = {
        "data_version": version,
        "sources": manifest["sources"],
        "attribution": notices["DATA_LICENSES.md"],
        "notices": notices,
        "input_provenance": {
            "dataset_manifest_sha256": sha256_file(dataset / "manifest.json")
        },
    }
    if family != "core":
        options["core_pack"] = str(output.parent / "core")
    value: Row = writer(str(dataset), family, str(output), options)
    paths = []
    for record in value["files"]:
        path = located(output, record["path"])
        if (
            path.stat().st_size != record["size"]
            or sha256_file(path) != record["sha256"]
        ):
            raise ValueError(f"Client pack checksum mismatch: {record['path']}")
        paths.append(path)
    saved = output / "manifest.json"
    if not saved.is_file():
        raise ValueError("Client writer did not publish its manifest")
    if read_json(saved) != value:
        raise ValueError("Client result differs from its saved manifest")
    verify_dataset(dataset)
    return [*paths, saved]
