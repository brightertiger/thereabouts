"""Activate a verified local dataset while retaining the preceding directory."""

import os
from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.golden.inputs import verify_record


def activate(workspace: Workspace, output: Path) -> None:
    """Keep artifact paths stable with a symlink; never delete the previous golden."""
    manifest = read_json(output / "manifest.json")
    if not manifest.get("completed") or manifest.get("schema_version") != "golden-2":
        raise ValueError("Only a verified golden-2 snapshot may be activated")
    for record in [*manifest["tables"], *manifest["verification_artifacts"]]:
        verify_record(record)
    active = workspace.root / "golden"
    if active.is_symlink() and active.resolve() == output.resolve():
        return
    backup = workspace.root / "golden-v1"
    if active.exists():
        if backup.exists() or active.is_symlink():
            raise ValueError(
                "Preserve existing golden and golden-v1; ambiguous activation"
            )
        active.rename(backup)
    # The retained v1 manifest must remain readable after its directory moves.
    if backup.exists():
        previous = read_json(backup / "manifest.json")
        original = backup / "manifest.original.json"
        if not original.exists():
            write_json(original, previous)
        for record in previous["tables"]:
            source = Path(record["path"])
            if source.is_relative_to(active):
                record["path"] = str(backup / source.relative_to(active))
        write_json(backup / "manifest.json", previous)
    temporary = workspace.root / "golden.next"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(output.resolve(), target_is_directory=True)
    os.replace(temporary, active)
    write_json(
        workspace.work / "v2-publication.json",
        {"completed": True, "active": str(output), "retained": str(backup)},
    )
