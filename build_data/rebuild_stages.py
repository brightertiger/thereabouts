"""Verified upstream reuse for the acquired-source to published-dataset controller."""

from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.manifests import load_manifest
from build_data.golden.inputs import Inputs, discover
from build_data.golden.paths import read
from build_data.golden.planning import inventory
from build_data.reconcile.common import builder_hash, policy
from build_data.reconcile.inputs import KINDS


def reconciled(workspace: Workspace) -> Inputs | None:
    """Reuse only current code/policy/source checkpoints covering the entire world."""
    path = workspace.root / "reconciled/manifest.json"
    if not path.exists():
        return None
    manifest = read_json(path)
    configured = policy()
    retained = manifest["policy"]
    # Reconciliation derives additional dependency sovereigns from source hierarchy.
    same_policy = all(
        retained.get(k) == v for k, v in configured.items() if k != "sovereigns"
    )
    same_sovereigns = all(
        retained["sovereigns"].get(k) == v for k, v in configured["sovereigns"].items()
    )
    sources = {source: load_manifest(workspace, source) for source in KINDS}
    if not (
        same_policy
        and same_sovereigns
        and manifest["builder"] == builder_hash()
        and manifest["sources"] == sources
    ):
        return None
    inputs = discover(workspace)
    expected = set(inventory(workspace, inputs)["expected"])
    return inputs if expected <= inputs.countries.keys() else None


def completed_base(workspace: Workspace, inputs: Inputs) -> Path | None:
    """Find a valid explicit snapshot, or freeze a completed base-stage output."""
    from build_data.normalize_cells.base import StaleBaseError, load, snapshot, validate

    if (workspace.root / "base_cells/current.json").exists():
        # Corruption is an error, never a reason to overwrite an active dataset.
        try:
            return load(workspace, inputs)[0]
        except StaleBaseError:
            # Keep the old snapshot; a newly built base gets its own directory.
            pass
    path = workspace.root / "golden/manifest.json"
    if not path.exists():
        return None
    manifest = read(path, workspace.root)
    if not manifest.get("completed"):
        return None
    try:
        validate(manifest, inputs)
    except StaleBaseError:
        return None
    return snapshot(workspace, path, inputs)
