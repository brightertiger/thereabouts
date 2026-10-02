"""Checkpoint the base cell stage independently of the active published dataset."""

from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import file_record
from build_data.acquire.io import sha256_file
from build_data.golden import paths as data_paths
from build_data.golden.cells import builder
from build_data.golden.inputs import Inputs, verify_record
from build_data.golden.ledger import Ledger
from build_data.reconcile.common import Row


class StaleBaseError(ValueError):
    """A valid old snapshot needs regeneration under current code or inputs."""


def validate(manifest: Row, inputs: Inputs) -> None:
    """Require complete base cells from the current reconciled inputs and cell code."""
    if (
        manifest.get("schema_version") != "golden-1"
        or not manifest.get("completed")
        or manifest["inputs"]["identity"] != inputs.identity
        or manifest["inputs"]["golden_builder"] != builder()
        or manifest["inputs"]["countries"] != inputs.countries
    ):
        raise StaleBaseError("Base cells do not match current reconciled inputs/code")


def snapshot(workspace: Workspace, source: Path, inputs: Inputs) -> Path:
    """Hard-link verified immutable tables; interrupted copies can safely resume."""
    original = data_paths.read(source, workspace.root)
    validate(original, inputs)
    digest = data_paths.digest(
        {"base": original, "code": sha256_file(Path(__file__))}, workspace.root
    )
    root = workspace.root / "base_cells" / digest
    manifest_path = root / "manifest.json"
    ledger = Ledger(workspace)
    if not ledger.is_complete("base-cells.snapshot", digest, digest):
        tables = []
        for record in original["tables"]:
            verify_record(record)
            name = data_paths.digest(record, workspace.root) + ".parquet"
            target = root / record["kind"] / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.hardlink_to(Path(record["path"]))
            copied = {**record, "path": str(target.resolve())}
            verify_record(copied)
            tables.append(copied)
        data_paths.write(
            manifest_path,
            {
                **original,
                "tables": tables,
                "source_snapshot": data_paths.digest(original, workspace.root),
                "data_root": data_paths.relative(workspace.root, root),
            },
            workspace.root,
        )
        ledger.complete("base-cells.snapshot", digest, digest, [manifest_path])
    data_paths.write(
        workspace.root / "base_cells/current.json",
        {"digest": digest, "manifest": file_record(manifest_path)},
        workspace.root,
    )
    return manifest_path


def load(workspace: Workspace, inputs: Inputs) -> tuple[Path, Row]:
    """Read a committed dependency, verifying table contents on every new process."""
    pointer = data_paths.read(
        workspace.root / "base_cells/current.json", workspace.root
    )
    record, digest = pointer["manifest"], pointer["digest"]
    verify_record(record)
    if not Ledger(workspace).is_complete("base-cells.snapshot", digest, digest):
        raise ValueError("Uncommitted base-cell snapshot")
    path = Path(record["path"])
    manifest = data_paths.read(path, workspace.root)
    validate(manifest, inputs)
    for table in manifest["tables"]:
        verify_record(table)
    return path, manifest
