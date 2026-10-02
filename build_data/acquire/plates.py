"""Pinned plate documents, raw query responses, and offline normalization."""

import shutil

from .artifacts import read_json
from .download import download_file
from .geonames_download import now
from .io import fingerprint, sha256_file, write_json
from .ledger import Ledger
from .plates_config import policy
from .plates_http import fetch
from .runtime import single_run, source_budget
from .workspace import Workspace


def download(workspace: Workspace) -> None:
    """Resume at pinned document boundaries; fail on changed upstream bytes."""
    with single_run(workspace, "plates"):
        specifications = policy("sources")
        root = workspace.raw("plates")
        inventory_path = root / "inventory.json"
        if inventory_path.exists():
            inventory = read_json(inventory_path)
            if any(
                specifications.get(k) != v
                for k, v in inventory["specifications"].items()
            ):
                raise ValueError("Plate source pins changed; use a new data directory")
            if inventory["specifications"] != specifications:
                inventory["specifications"] = specifications
                inventory["source_release"] = fingerprint(specifications)
                inventory.pop("completed_at", None)
                write_json(inventory_path, inventory)
        else:
            inventory = dict(
                source="plates",
                source_release=fingerprint(specifications),
                specifications=specifications,
                files={},
                started_at=now(),
            )
            write_json(inventory_path, inventory)
        ledger = Ledger(workspace.ledger_path)
        for name, specification in specifications.items():
            target = root / "snapshot" / name
            pin = {**specification, "path": str(target.resolve())}
            digest = fingerprint(pin)
            if ledger.is_complete("plates.download", name, digest):
                continue
            source_budget(workspace, "plates", pin["size"])
            target.parent.mkdir(parents=True, exist_ok=True)
            research = root / "research" / name
            if (
                not target.exists()
                and research.exists()
                and sha256_file(research) == pin["sha256"]
            ):
                shutil.copyfile(research, target)
            if not target.exists():
                print(f"DOWNLOAD plates/{name}", flush=True)
                if pin.get("range_verified"):
                    download_file(
                        pin["download_url"],
                        target,
                        expected_size=pin["size"],
                        etag=pin.get("etag"),
                        last_modified=pin.get("last_modified"),
                        sha256=pin["sha256"],
                        backoff=2,
                    )
                else:
                    fetch(
                        root / "snapshot",
                        name,
                        pin["download_url"],
                        interval=65 if pin.get("kind") == "wikidata" else 1.1,
                    )
            if (
                target.stat().st_size != pin["size"]
                or sha256_file(target) != pin["sha256"]
            ):
                raise ValueError(
                    f"Snapshot changed: {name}; restore the retained raw snapshot. "
                    "A new query/revision needs a deliberately reviewed new pin."
                )
            inventory["files"][name] = pin
            write_json(inventory_path, inventory)
            ledger.complete("plates.download", name, digest, [target])
        if "completed_at" not in inventory:
            inventory["completed_at"] = now()
            write_json(inventory_path, inventory)
        print(f"plates: {len(specifications)} pinned documents verified", flush=True)


def normalize(workspace: Workspace) -> None:
    from .plates_normalize import normalize as run

    run(workspace)
