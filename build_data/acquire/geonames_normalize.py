"""Geonames normalize."""

from __future__ import annotations

import time
from contextlib import closing
from pathlib import Path
from typing import cast

from . import Workspace, fingerprint
from .artifacts import publish_report
from .geonames_download import SOURCE, now, read_json
from .geonames_index import _connect, build_index
from .geonames_reader import extract
from .geonames_report import summarize
from .geonames_rows import Row
from .geonames_settings import (
    configuration,
)
from .geonames_statistics import artifacts, comparison
from .geonames_tsv import chunks
from .geonames_units import normalize_chunk
from .lifecycle import finish_source, resume_source
from .runtime import resources, single_run
from .schemas import Kind


def normalize(workspace: Workspace) -> None:
    """Publish all P/A points and their aliases, with reproducible audit metadata."""
    with single_run(workspace, SOURCE):
        if resume_source(workspace, SOURCE, configuration()):
            return
        started = time.monotonic()
        inventory = read_json(workspace.raw(SOURCE) / "inventory.json")
        if "completed_at" not in inventory:
            raise ValueError("GeoNames download is not complete")
        digest = fingerprint({"inventory": inventory, **configuration()})
        inputs = extract(workspace, inventory)
        index = build_index(workspace, inputs, inventory, digest)
        units: list[Row] = []
        reports: list[Path] = []
        with closing(_connect(index, readonly=True)) as db:
            for kind, member in (
                ("places", "allCountries.txt"),
                ("names", "alternateNamesV2.txt"),
            ):
                for chunk in chunks(inputs[member]):
                    unit, report = normalize_chunk(
                        workspace,
                        inputs[member],
                        chunk,
                        cast(Kind, kind),
                        db,
                        inventory,
                        digest,
                    )
                    units.append(unit)
                    reports.append(report)
            verification = summarize(reports, inputs, db)
        verification["publisher_statistics"] = comparison(
            workspace,
            cast(dict[str, int], verification["source_classes"]),
            cast(dict[str, int], verification["feature_codes"]),
        )
        auxiliary = [
            p
            for name, p in inputs.items()
            if name not in ("allCountries.txt", "alternateNamesV2.txt")
        ]
        auxiliary.extend(artifacts(workspace))
        verification["seconds_this_run"] = round(time.monotonic() - started, 3)
        verification["completed_at"] = now()
        verification.update(resources(started))
        report_path = publish_report(workspace, SOURCE, verification)
        pins = cast(dict[str, Row], inventory["files"])
        finish_source(
            workspace,
            SOURCE,
            str(inventory["source_release"]),
            units,
            [*auxiliary, report_path],
            configuration(),
            inputs=[Path(str(pin["path"])) for pin in pins.values()],
        )
        print(f"GeoNames normalization complete: {verification['counts']}", flush=True)
