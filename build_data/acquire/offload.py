"""Explicit remote raw custody; normalized artifacts still verify locally."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import read_json, verify_files
from .io import fingerprint, write_json
from .ledger import Ledger
from .runtime import single_run
from .workspace import Workspace


def state_path(workspace: Workspace, source: str) -> Path:
    return workspace.work / "offloaded" / f"{source}.json"


def state(workspace: Workspace, source: str) -> dict[str, Any] | None:
    path = state_path(workspace, source)
    if not path.exists():
        return None
    value = read_json(path)
    if value.get("version") != 1 or value.get("source") != source:
        raise ValueError(f"Invalid offload state: {path}")
    return value if value["offloaded"] else None


def applies(workspace: Workspace, source: str, manifest: dict[str, Any]) -> bool:
    record = state(workspace, source)
    return bool(record and record["manifest_sha256"] == fingerprint(manifest))


def verify_dependencies(
    workspace: Workspace, source: str, manifest: dict[str, Any]
) -> None:
    """Allow only missing raw inputs covered by this exact offload snapshot."""
    offloaded = applies(workspace, source, manifest)
    raw = workspace.raw(source).resolve()
    for record in [manifest["inventory"], *manifest["inputs"], *manifest["auxiliary"]]:
        path = Path(record["path"])
        if offloaded and not path.exists() and path.resolve().is_relative_to(raw):
            continue
        verify_files([record])


def offload(
    workspace: Workspace, source: str, remote: str, *, record_existing: bool = False
) -> None:
    """Sync raw custody or record an already verified transfer; never delete files."""
    if not remote.startswith("gs://") or remote.rstrip("/").count("/") < 3:
        raise ValueError("Provide a gs://bucket/prefix destination")
    from .manifests import load_manifest
    from .status import source_status

    with single_run(workspace, source):
        manifest = read_json(workspace.normalized(source) / "manifest.json")
        if source_status(workspace, source)["normalize"] != "complete":
            raise ValueError("Offload requires complete normalized outputs")
        if not record_existing:
            load_manifest(workspace, source)
            subprocess.run(
                [
                    "gcloud",
                    "storage",
                    "rsync",
                    "--recursive",
                    str(workspace.raw(source)),
                    remote,
                ],
                check=True,
            )
        # Recording existing custody is explicit operator evidence, not a claim
        # that this command verified remote checksums or transferred missing bytes.
        value = {
            "version": 1,
            "source": source,
            "offloaded": True,
            "remote": remote.rstrip("/"),
            "manifest_sha256": fingerprint(manifest),
            "recorded_at": datetime.now(UTC).isoformat(),
            "verification": "operator verified count and bytes"
            if record_existing
            else "gcloud storage rsync",
        }
        path = state_path(workspace, source)
        previous = path.read_bytes() if path.exists() else None
        write_json(path, value)
        try:
            load_manifest(workspace, source)
        except (ValueError, OSError):
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                write_json(path, json.loads(previous))
            raise


def restore(workspace: Workspace, source: str) -> None:
    from .manifests import load_manifest

    with single_run(workspace, source):
        record = state(workspace, source)
        if record is None:
            raise ValueError(f"No offloaded snapshot for {source}")
        manifest = read_json(workspace.normalized(source) / "manifest.json")
        if record["manifest_sha256"] != fingerprint(manifest):
            raise ValueError("Normalized snapshot changed since offload")
        required = sum(
            r["size"] for r in manifest["inputs"] if not Path(r["path"]).exists()
        )
        workspace.check_budget(required)
        subprocess.run(
            [
                "gcloud",
                "storage",
                "rsync",
                "--recursive",
                record["remote"],
                str(workspace.raw(source)),
            ],
            check=True,
        )
        verify_files(
            [manifest["inventory"], *manifest["inputs"], *manifest["auxiliary"]]
        )
        load_manifest(workspace, source)
        record.update(offloaded=False, restored_at=datetime.now(UTC).isoformat())
        write_json(state_path(workspace, source), record)
        Ledger(workspace.ledger_path).complete(
            f"{source}.restore",
            "current",
            fingerprint(record),
            [state_path(workspace, source)],
        )
