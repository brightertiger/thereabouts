"""Geoboundaries normalize."""

from __future__ import annotations

import gc
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

import shapefile
import shapely

from . import SCHEMA_HASHES, Ledger, Workspace, fingerprint, sha256_file
from .artifacts import publish_report
from .geoboundaries_config import DOWNLOAD_VERSION, SOURCE, _unit
from .geoboundaries_http import _read
from .geoboundaries_inventory import _inventory_path, _license_path
from .geoboundaries_pins import _archive_path, _pin_path
from .geoboundaries_report import _summary
from .geoboundaries_settings import (
    BUILDER_VERSION,
    MAX_GEOMETRY_BYTES,
    MAX_SHAPE_BYTES,
    POLICY_VERSION,
    configuration,
)
from .geoboundaries_units import _convert
from .io import write_json
from .lifecycle import finish_source, resume_source
from .runtime import peak_rss_bytes, source_budget


def normalize_layers(workspace: Workspace) -> None:
    if resume_source(workspace, SOURCE, configuration()):
        return
    started = time.monotonic()
    inventory = _read(_inventory_path(workspace))
    ledger = Ledger(workspace.ledger_path)
    units: list[dict[str, str]] = []
    reports: list[dict[str, Any]] = []
    audits: list[Path] = []
    failed: dict[str, str] = {}
    for metadata in inventory["layers"]:
        unit = _unit(metadata)
        temporary = workspace.work / SOURCE / unit
        try:
            pin = _read(_pin_path(workspace, metadata))
            download_hash = fingerprint({"pin": pin, "builder": DOWNLOAD_VERSION})
            if not ledger.is_complete(f"{SOURCE}.download", unit, download_hash):
                raise ValueError("Download unit is not verified complete")
            pin["archive_sha256"] = sha256_file(_archive_path(workspace, pin))
            country = (
                inventory["country_reference"]
                .get(metadata["boundaryISO"], {})
                .get("alpha2")
            )
            inputs_hash = fingerprint(
                {
                    "pin": pin,
                    "builder": BUILDER_VERSION,
                    "policy": POLICY_VERSION,
                    "schema": SCHEMA_HASHES["areas"],
                    "country": country,
                    "max_geometry_bytes": MAX_GEOMETRY_BYTES,
                    "max_shape_bytes": MAX_SHAPE_BYTES,
                }
            )
            audit = (
                workspace.normalized(SOURCE) / "audits" / inputs_hash / f"{unit}.json"
            )
            if not ledger.is_complete(f"{SOURCE}.normalize", unit, inputs_hash):
                with zipfile.ZipFile(_archive_path(workspace, pin)) as archive:
                    expanded = sum(
                        info.file_size
                        for info in archive.infolist()
                        if info.filename.endswith((".shp", ".shx", ".dbf", ".prj"))
                        and "_simplified" not in info.filename
                    )
                source_budget(workspace, SOURCE, expanded * 3)
                print(f"NORMALIZE {unit}", flush=True)
                outputs, report = _convert(
                    workspace, pin, country, inputs_hash, temporary
                )
                write_json(audit, report)
                ledger.complete(
                    f"{SOURCE}.normalize",
                    unit,
                    inputs_hash,
                    [*outputs, audit],
                    metadata={
                        key: report[key]
                        for key in (
                            "input_features",
                            "output_rows",
                            "invalid_input",
                            "reject_count",
                            "parquet_bytes",
                            "partitions",
                        )
                    },
                )
                shutil.rmtree(temporary)
            report = _read(audit)
            units.append(
                {
                    "stage": f"{SOURCE}.normalize",
                    "unit_id": unit,
                    "inputs_hash": inputs_hash,
                }
            )
            reports.append(report)
            audits.append(audit)
            print(
                f"NORMALIZED {unit}: {report['input_features']} features, "
                f"{report['output_rows']} rows, {report['reject_count']} rejects",
                flush=True,
            )
        except (
            OSError,
            ValueError,
            zipfile.BadZipFile,
            shapely.errors.GEOSException,
            shapefile.ShapefileException,
        ) as error:
            failed[unit] = f"{type(error).__name__}: {error}"
            print(f"FAILED NORMALIZE {unit}: {error}", flush=True)
        gc.collect()
    summary = _summary(inventory, reports, failed)
    summary["elapsed_seconds"] = time.monotonic() - started
    summary["peak_rss_bytes"] = max(
        peak_rss_bytes(),
        max((int(report["peak_rss_bytes"]) for report in reports), default=0),
    )
    summary_path = publish_report(workspace, SOURCE, summary)
    if failed:
        raise RuntimeError(
            f"{len(failed)} incomplete geoBoundaries units; see {summary_path}"
        )
    finish_source(
        workspace,
        SOURCE,
        inventory["source_release"],
        units,
        [summary_path, _license_path(workspace), *audits],
        configuration(),
        inputs=[_pin_path(workspace, layer) for layer in inventory["layers"]],
    )
    print(
        f"MANIFEST COMPLETE: {len(units)} layers; {summary['output_rows']} rows",
        flush=True,
    )
