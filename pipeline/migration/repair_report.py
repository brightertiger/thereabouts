"""Classify every metadata change, distinguishing the explicit migration set."""

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import cast

from pipeline.runtime.jsonio import JSON, Object

from .layout import NORMALIZED, OFFLOADED, PILOT


def file_class(name: str, *, created: bool = False) -> str:
    parts = PurePosixPath(name).parts
    if created:
        return "imported repository evidence"
    if name.startswith(NORMALIZED + "/"):
        return (
            "normalized source manifest"
            if parts[-1] == "manifest.json"
            else "normalized auxiliary metadata"
        )
    if name.startswith("raw/"):
        return "raw source inventory"
    if name.startswith("city_normalized/"):
        return "city manifest" if len(parts) == 2 else "city country metadata"
    if name.startswith(OFFLOADED + "/"):
        return "source custody receipt"
    if name.startswith(PILOT + "/"):
        return "pilot gate receipt" if "gate" in parts[-1] else "pilot summary"
    if name.startswith("golden-base-"):
        return "retained base manifest"
    if name.startswith("golden-"):
        return "active dataset metadata"
    return "other retained metadata"


def in_spec(name: str) -> bool:
    return (
        (
            name.startswith(NORMALIZED + "/")
            and name.endswith("/manifest.json")
            and len(PurePosixPath(name).parts) == 3
        )
        or name == "city_normalized/manifest.json"
        or name == PILOT + "/gate.json"
        or name == "raw/ghsl/inventory.json"
    )


def summarize(details: Sequence[Object]) -> Object:
    classes: dict[str, JSON] = {}
    for item in details:
        category = str(item["class"])
        group = cast(
            Object,
            classes.setdefault(
                category,
                {
                    "files": 0,
                    "outside_spec": 0,
                    "paths_rewritten": 0,
                    "hashes_cascaded": 0,
                    "sizes_cascaded": 0,
                    "tables_repointed": 0,
                },
            ),
        )
        group["files"] = cast(int, group["files"]) + 1
        group["outside_spec"] = cast(int, group["outside_spec"]) + (not item["in_spec"])
        for key, count in cast(Object, item["repairs"]).items():
            group[key] = cast(int, group[key]) + cast(int, count)
    return classes
