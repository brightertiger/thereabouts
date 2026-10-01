"""Geoboundaries."""

from __future__ import annotations

import time
import zipfile
from datetime import UTC, datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any

from . import Ledger, Workspace, download_file, fingerprint
from .geoboundaries_config import DOWNLOAD_VERSION, SOURCE, _unit
from .geoboundaries_inventory import _inventory
from .geoboundaries_pins import _archive_path, _pin
from .io import write_json
from .lifecycle import resume_download
from .runtime import single_run, source_budget


def _archive_check(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"ZIP CRC failure: {bad}")
        names = archive.namelist()
        if not any(name.endswith(".shp") for name in names):
            raise ValueError("Layer ZIP contains no shapefile")
        return {
            "zip_crc": "passed",
            "members": names,
            "expanded_bytes": sum(info.file_size for info in archive.infolist()),
        }


def _download(workspace: Workspace) -> None:
    started = time.monotonic()
    inventory = _inventory(workspace)
    ledger = Ledger(workspace.ledger_path)
    report_path = workspace.work / f"{SOURCE}-download-report.json"
    report: dict[str, Any] = {
        "source_release": inventory["source_release"],
        "started_at": datetime.now(UTC).isoformat(),
        "completed": {},
        "failed": {},
        "finished": False,
    }
    for layer in inventory["layers"]:
        unit = _unit(layer)
        try:
            pin = _pin(workspace, layer)
            inputs_hash = fingerprint({"pin": pin, "builder": DOWNLOAD_VERSION})
            path = _archive_path(workspace, pin)
            if not ledger.is_complete(f"{SOURCE}.download", unit, inputs_hash):
                source_budget(workspace, SOURCE, int(pin["size"]) * 2)
                print(f"DOWNLOAD {unit} {pin['size']} bytes", flush=True)
                download_file(
                    str(pin["url"]),
                    path,
                    expected_size=int(pin["size"]),
                    etag=str(pin["etag"]),
                )
                checked = _archive_check(path)
                ledger.complete(
                    f"{SOURCE}.download", unit, inputs_hash, [path], metadata=checked
                )
            report["completed"][unit] = {"path": str(path), "size": path.stat().st_size}
            print(
                f"VERIFIED {unit} ({len(report['completed'])}/"
                f"{len(inventory['layers'])})",
                flush=True,
            )
        except (OSError, ValueError, HTTPException, zipfile.BadZipFile) as error:
            report["failed"][unit] = f"{type(error).__name__}: {error}"
            print(f"FAILED {unit}: {error}", flush=True)
        report["elapsed_seconds"] = time.monotonic() - started
        write_json(report_path, report)
    report["finished"] = True
    write_json(report_path, report)
    if report["failed"]:
        raise RuntimeError(
            f"{len(report['failed'])} geoBoundaries layers failed; see {report_path}"
        )


def download(workspace: Workspace) -> None:
    """Download immutable, CRC-verified layer ZIPs; retry failed units on rerun."""
    with single_run(workspace, SOURCE):
        if resume_download(workspace, SOURCE):
            return
        _download(workspace)


def normalize(workspace: Workspace) -> None:
    """Publish bounded areas; implemented in the source-owned normalization helper."""
    from .geoboundaries_normalize import normalize_layers

    with single_run(workspace, SOURCE), single_run(workspace, "geometry"):
        normalize_layers(workspace)
