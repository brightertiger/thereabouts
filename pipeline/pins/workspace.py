"""Bootstrap pins from the exact inventories and input hashes used by a build."""

import json
from pathlib import Path
from typing import Any

from pipeline.migration.paths import legacy_relative
from pipeline.runtime.jsonio import digest, sha256_file
from pipeline.runtime.paths import located

from .models import PinFile, SourcePin

Row = dict[str, Any]


def workspace_name(name: str, root: Path) -> str:
    if name.startswith("data/"):
        name = name.removeprefix("data/")
    return legacy_relative(name, root)


def portable(value: Any, root: Path, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {name: portable(item, root, key=name) for name, item in value.items()}
    if isinstance(value, list):
        return [portable(item, root, key=key) for item in value]
    if isinstance(value, str) and key in {"path", "local"}:
        return workspace_name(value, root)
    return value


def verified_json(root: Path, record: Row) -> Row:
    path = located(root, workspace_name(record["path"], root))
    if path.stat().st_size != record["size"] or sha256_file(path) != record["sha256"]:
        raise ValueError(f"Manifest references changed metadata: {record['path']}")
    value: Row = json.loads(path.read_bytes())
    return value


def _file(source: str, spec: Row, record: Row, root: Path) -> PinFile:
    path = workspace_name(record["path"], root)
    prefix = f"raw/{source}/"
    if not path.startswith(prefix):
        raise ValueError(f"Raw input escapes source {source}: {path}")
    metadata = portable(
        {
            k: v
            for k, v in spec.items()
            if k
            not in {"path", "url", "size", "sha256", "etag", "last_modified", "local"}
        },
        root,
    )
    return PinFile(
        path.removeprefix(prefix),
        str(spec["download_url"] if "download_url" in spec else spec["url"]),
        int(record["size"]),
        str(record["sha256"]),
        spec.get("etag"),
        spec.get("last_modified"),
        metadata,
    )


def from_manifest(root: Path, manifest: Row) -> SourcePin:
    source = str(manifest["source"])
    inventory = verified_json(root, manifest["inventory"])
    if "pin_metadata" in inventory:
        return reconstructed_pin(inventory, manifest, root)
    inputs = {workspace_name(r["path"], root): r for r in manifest["inputs"]}
    specs: dict[str, Row] = {}
    commits: dict[str, str] = {}
    for key, spec in inventory.get("files", {}).items():
        specs[workspace_name(spec["path"], root)] = {**spec, "key": key}
    for obj in inventory.get("objects", []):
        specs[f"raw/{source}/{obj['relative_path']}"] = obj
    if source == "osm_land":
        archives = [name for name in inputs if name.endswith(".zip")]
        if len(archives) != 1:
            raise ValueError("OSM land manifest must pin exactly one archive")
        specs[archives[0]] = {**inventory, "url": inventory["source_url"]}
    if source == "geoboundaries":
        for name, record in inputs.items():
            if name.startswith(f"raw/{source}/pins/") and name.endswith(".json"):
                layer_pin = verified_json(root, record)
                layer = layer_pin["metadata"]
                key = f"{layer['boundaryISO']}-{layer['boundaryType']}"
                archive = f"raw/{source}/{layer_pin['commit']}/{key}.zip"
                specs[archive] = layer_pin
                commits[key] = layer_pin["commit"]
    files = []
    for name, spec in sorted(specs.items()):
        if name not in inputs:
            raise ValueError(
                f"Inventory input is absent from the source manifest: {name}"
            )
        files.append(_file(source, spec, inputs[name], root))
    metadata: Row = {
        "inventory_name": workspace_name(
            manifest["inventory"]["path"], root
        ).removeprefix(f"raw/{source}/"),
        "inventory_fingerprint": digest(portable(inventory, root)),
    }
    if "country_reference" in inventory:
        metadata["country_reference"] = inventory["country_reference"]
    if commits:
        metadata["commits"] = commits
    if source == "geonames":
        metadata["dump_date"] = inventory["source_release"][:8]
    if source == "overture":
        metadata["objects"] = len(files)
    retrieved = inventory.get("retrieved_at", inventory.get("completed_at"))
    if retrieved is None:
        dates = [
            str(item.metadata["retrieved_at"])
            for item in files
            if item.metadata.get("retrieved_at")
        ]
        if not dates:
            raise ValueError(f"Source {source} has no recorded retrieval date")
        retrieved = min(dates)
    result = SourcePin(
        str(manifest["source_release"]),
        str(retrieved),
        files=files,
        metadata=metadata,
    )
    result.validate()
    return result


def reconstructed_pin(inventory: Row, manifest: Row, root: Path) -> SourcePin:
    inputs = {workspace_name(r["path"], root): r for r in manifest["inputs"]}
    files = []
    for record in inventory["files"].values():
        name = workspace_name(record["path"], root)
        if name not in inputs or any(
            record[field] != inputs[name][field] for field in ("size", "sha256")
        ):
            raise ValueError(f"Inventory differs from manifest input: {name}")
        files.append(PinFile(**{k: v for k, v in record.items() if k != "path"}))
    result = SourcePin(
        str(inventory["source_release"]),
        str(inventory["pinned_at"]),
        files=files,
        metadata=inventory["pin_metadata"],
    )
    result.validate()
    return result
