"""One committed manifest format and the only consumer entry point for partitions."""

from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .artifacts import file_record, file_records, read_json, verify_files
from .io import fingerprint, write_json
from .ledger import Ledger
from .offload import verify_dependencies
from .schemas import SCHEMAS, Kind
from .workspace import Workspace

MANIFEST_VERSION = 2


def inventory_path(workspace: Workspace, source: str) -> Path:
    resolved = workspace.raw(source) / "inventory-resolved.json"
    return resolved if resolved.exists() else workspace.raw(source) / "inventory.json"


def _partition_kind(workspace: Workspace, source: str, path: Path) -> Kind:
    relative = path.resolve().relative_to(workspace.normalized(source).resolve())
    if len(relative.parts) != 3 or relative.parts[0] not in SCHEMAS:
        raise ValueError(f"Partition outside the source layout: {path}")
    return relative.parts[0]


def publish_manifest(
    workspace: Workspace,
    source: str,
    release: str,
    units: Sequence[Mapping[str, Any]],
    auxiliary: Sequence[Path],
    configuration: Mapping[str, object],
    *,
    inputs: Sequence[Path] = (),
) -> dict[str, Any]:
    """Verify every unit before atomically replacing the source's commit record.

    Only validated ledger outputs enter the partition list. A consumer does not
    need to interpret source-specific audit keys or glob fingerprint directories.
    """
    ledger = Ledger(workspace.ledger_path)
    partitions: list[dict[str, Any]] = []
    artifacts = list(auxiliary)
    rows: Counter[str] = Counter()
    seen: set[Path] = set()
    for unit in units:
        if unit["stage"] != f"{source}.normalize":
            raise ValueError("Manifest unit belongs to another source or stage")
        outputs = ledger.completed_outputs(
            unit["stage"], unit["unit_id"], unit["inputs_hash"]
        )
        if outputs is None:
            raise ValueError(f"Unverified normalization unit: {unit['unit_id']}")
        for path in outputs:
            if path.suffix != ".parquet":
                artifacts.append(path)
                continue
            if path in seen:
                raise ValueError(f"Duplicate manifest partition: {path}")
            seen.add(path)
            kind = _partition_kind(workspace, source, path)
            with pq.ParquetFile(path) as parquet:
                if not parquet.schema_arrow.equals(SCHEMAS[kind], check_metadata=False):
                    raise ValueError(f"Wrong partition schema: {path}")
                count = parquet.metadata.num_rows
            partitions.append({**file_record(path), "kind": kind, "rows": count})
            rows[kind] += count
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "schema_version": "1",
        "source": source,
        "source_release": release,
        "configuration": dict(configuration),
        "inventory": file_record(inventory_path(workspace, source)),
        "inputs": file_records(inputs),
        "units": [dict(unit) for unit in units],
        "partitions": partitions,
        "rows": dict(rows),
        "bytes": sum(part["size"] for part in partitions),
        "auxiliary": file_records(artifacts),
    }
    path = workspace.normalized(source) / "manifest.json"
    write_json(path, manifest)
    ledger.complete(f"{source}.manifest", "current", fingerprint(manifest), [path])
    return manifest


def load_manifest(workspace: Workspace, source: str) -> dict[str, Any]:
    """Verify the inventory, inputs, outputs and ledger without changing them."""
    manifest = read_json(workspace.normalized(source) / "manifest.json")
    if (
        manifest.get("manifest_version") != MANIFEST_VERSION
        or manifest.get("source") != source
    ):
        raise ValueError("Unsupported manifest version or source; run normalization")
    ledger = Ledger(workspace.ledger_path)
    if not ledger.is_complete(f"{source}.manifest", "current", fingerprint(manifest)):
        raise ValueError("Manifest has no matching verified commit")
    expected_inventory = inventory_path(workspace, source).resolve()
    if Path(manifest["inventory"]["path"]).resolve() != expected_inventory:
        raise ValueError("Manifest refers to a superseded inventory")
    verify_dependencies(workspace, source, manifest)
    if read_json(expected_inventory)["source_release"] != manifest["source_release"]:
        raise ValueError("Manifest release differs from pinned inventory")
    paths: set[Path] = set()
    for unit in manifest["units"]:
        if unit["stage"] != f"{source}.normalize":
            raise ValueError("Manifest has a foreign unit")
        outputs = ledger.completed_outputs(**unit)
        if outputs is None:
            raise ValueError(f"Unverified normalization unit: {unit['unit_id']}")
        paths.update(path.resolve() for path in outputs if path.suffix == ".parquet")
    listed: set[Path] = set()
    rows: Counter[str] = Counter()
    for record in manifest["partitions"]:
        path = Path(record["path"]).resolve()
        if path in listed or _partition_kind(workspace, source, path) != record["kind"]:
            raise ValueError("Duplicate or incorrectly classified partition")
        listed.add(path)
        with pq.ParquetFile(path) as parquet:
            if parquet.metadata.num_rows != record["rows"]:
                raise ValueError(f"Manifest row count differs from partition: {path}")
        rows[record["kind"]] += record["rows"]
    if (
        listed != paths
        or dict(rows) != manifest["rows"]
        or sum(part["size"] for part in manifest["partitions"]) != manifest["bytes"]
    ):
        raise ValueError("Manifest partitions disagree with committed units/counts")
    verify_files(manifest["partitions"])
    return manifest


def current_partitions(
    workspace: Workspace, source: str, kind: Kind
) -> tuple[Path, ...]:
    """Return only verified current files of a kind; never include orphan partitions."""
    if kind not in SCHEMAS:
        raise ValueError(f"Unknown partition kind: {kind}")
    manifest = load_manifest(workspace, source)
    return tuple(
        Path(part["path"]) for part in manifest["partitions"] if part["kind"] == kind
    )
