"""Checkpoint the base cell stage independently of the active published dataset."""

from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import file_record, read_json
from build_data.acquire.io import fingerprint, sha256_file, write_json
from build_data.golden.cells import builder
from build_data.golden.inputs import Inputs, verify_record
from build_data.reconcile.common import Row


def validate(manifest: Row, inputs: Inputs) -> None:
    """Require complete base cells from the current reconciled inputs and cell code."""
    if (
        manifest.get("schema_version") != "golden-1"
        or not manifest.get("completed")
        or manifest["inputs"]["identity"] != inputs.identity
        or manifest["inputs"]["golden_builder"] != builder()
        or manifest["inputs"]["countries"] != inputs.countries
    ):
        raise ValueError("Base cells do not match current reconciled inputs/code")


def snapshot(workspace: Workspace, source: Path, inputs: Inputs) -> Path:
    """Hard-link verified immutable tables; interrupted copies can safely resume."""
    original = read_json(source)
    validate(original, inputs)
    digest = fingerprint({"base": original, "code": sha256_file(Path(__file__))})
    root = workspace.root / "base_cells" / digest
    manifest_path = root / "manifest.json"
    ledger = Ledger(workspace.ledger_path)
    if not ledger.is_complete("base-cells.snapshot", digest, digest):
        tables = []
        for record in original["tables"]:
            verify_record(record)
            name = fingerprint(record) + ".parquet"
            target = root / record["kind"] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.hardlink_to(Path(record["path"]))
            copied = {**record, "path": str(target.resolve())}
            verify_record(copied)
            tables.append(copied)
        write_json(
            manifest_path,
            {**original, "tables": tables, "source_snapshot": fingerprint(original)},
        )
        ledger.complete("base-cells.snapshot", digest, digest, [manifest_path])
    write_json(
        workspace.root / "base_cells/current.json",
        {"digest": digest, "manifest": file_record(manifest_path)},
    )
    return manifest_path


def load(workspace: Workspace, inputs: Inputs) -> tuple[Path, Row]:
    """Read a committed dependency, verifying table contents on every new process."""
    pointer = read_json(workspace.root / "base_cells/current.json")
    record, digest = pointer["manifest"], pointer["digest"]
    verify_record(record)
    if not Ledger(workspace.ledger_path).is_complete(
        "base-cells.snapshot", digest, digest
    ):
        raise ValueError("Uncommitted base-cell snapshot")
    path = Path(record["path"])
    manifest = read_json(path)
    validate(manifest, inputs)
    for table in manifest["tables"]:
        verify_record(table)
    return path, manifest
