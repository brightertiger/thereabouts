"""Frozen inventories and independently resumable files for lookup sources."""

import gzip
import hashlib
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .artifacts import read_json
from .download import download_file
from .geonames_download import now
from .io import fingerprint, sha256_file, write_json
from .ledger import Ledger
from .lifecycle import resume_download
from .lookup_catalog import catalog
from .lookup_http import probe
from .runtime import single_run, source_budget
from .workspace import Workspace


def _local_geonames(workspace: Workspace, name: str) -> Path | None:
    path = workspace.raw("geonames") / "inventory.json"
    if not path.exists():
        return None
    pin = read_json(path).get("files", {}).get(name, {})
    candidate = Path(pin.get("path", "/missing"))
    if candidate.is_file() and pin.get("sha256") == sha256_file(candidate):
        return candidate
    return None


def download(workspace: Workspace, source: str) -> None:
    """Keep upstream bytes, licences and receipts; never change a frozen pin."""
    with single_run(workspace, source):
        if resume_download(workspace, source):
            return
        root = workspace.raw(source)
        path = root / "inventory.json"
        if path.exists():
            inventory = read_json(path)
        else:
            inventory = dict(
                source=source,
                source_release=now(),
                files={},
                specifications=catalog(source),
                started_at=now(),
            )
            write_json(path, inventory)
        ledger = Ledger(workspace.ledger_path)
        for name, specification in inventory["specifications"].items():
            if name not in inventory["files"]:
                local = _local_geonames(workspace, name) if source == "codes" else None
                pin = {
                    **specification,
                    **(
                        dict(
                            size=local.stat().st_size,
                            local=str(local),
                            sha256=sha256_file(local),
                            retrieved_at=now(),
                        )
                        if local
                        else probe(specification["url"])
                    ),
                }
                pin["path"] = str((root / "snapshot" / name).resolve())
                inventory["files"][name] = pin
                write_json(path, inventory)
            pin = inventory["files"][name]
            digest = fingerprint(pin)
            if ledger.is_complete(f"{source}.download", name, digest):
                continue
            target = Path(pin["path"])
            source_budget(workspace, source, pin["size"])
            print(f"DOWNLOAD {source}/{name} ({pin['size']:,} bytes)", flush=True)
            if "local" in pin:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(pin["local"], target)
                if sha256_file(target) != pin["sha256"]:
                    raise ValueError("Changed local reference")
            else:
                download_file(
                    pin["url"],
                    target,
                    expected_size=pin["size"],
                    etag=pin["etag"],
                    last_modified=pin["last_modified"],
                    retries=60,
                )
            evidence: dict[str, Any] = {"sha256": sha256_file(target)}
            if target.suffix == ".zip":
                with zipfile.ZipFile(target) as archive:
                    if archive.testzip() is not None:
                        raise ValueError(f"Corrupt ZIP: {target}")
                    evidence["members"] = [
                        {"name": i.filename, "bytes": i.file_size}
                        for i in archive.infolist()
                    ]
            if "git_blob" in pin:
                blob = hashlib.sha1(f"blob {pin['size']}\0".encode())
                with target.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        blob.update(block)
                if blob.hexdigest() != pin["git_blob"]:
                    raise ValueError("Git blob checksum mismatch")
            if "publisher_md5" in pin:
                with gzip.open(target, "rb") as stream:
                    checksum = hashlib.file_digest(stream, "md5").hexdigest()
                if checksum != pin["publisher_md5"]:
                    raise ValueError("Publisher MD5 mismatch")
                evidence["publisher_md5_verified"] = True
            ledger.complete(
                f"{source}.download", name, digest, [target], metadata=evidence
            )
        if "completed_at" not in inventory:
            inventory["completed_at"] = now()
            write_json(path, inventory)
        print(f"{source}: downloads complete", flush=True)
