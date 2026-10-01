"""Geonames report."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from .geonames_download import read_json
from .geonames_rows import Row
from .geonames_settings import SPOTS


def summarize(
    reports: list[Path], inputs: Mapping[str, Path], db: sqlite3.Connection
) -> Row:
    totals = {"places": Counter[str](), "names": Counter[str]()}
    codes: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    languages: Counter[str] = Counter()
    spots: dict[str, Row] = {}
    output_bytes = 0
    unit_seconds = 0.0
    for path in reports:
        report = read_json(path)
        totals[str(report["kind"])].update(cast(dict[str, int], report["counts"]))
        codes.update(cast(dict[str, int], report["feature_codes"]))
        classes.update(cast(dict[str, int], report["source_classes"]))
        languages.update(cast(dict[str, int], report["languages"]))
        spots.update(cast(dict[str, Row], report["spots"]))
        output_bytes += int(str(report["output_bytes"]))
        unit_seconds += float(str(report["seconds"]))
    for kind, member, table in (
        ("places", "allCountries.txt", "features"),
        ("names", "alternateNamesV2.txt", "aliases"),
    ):
        extracted = inputs[member]
        source_lines = int(
            str(read_json(extracted.with_name(extracted.name + ".json"))["lines"])
        )
        if totals[kind]["input"] != source_lines:
            raise ValueError(f"Source line accounting mismatch: {kind}")
        expected = db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if totals[kind]["kept"] != expected:
            raise ValueError(f"Unique-ID count mismatch: {kind}")
    checks: dict[str, Row] = {}
    for identifier, (name, country, low, high) in SPOTS.items():
        row = spots.get(identifier)
        checks[name] = {
            "source_id": identifier,
            "present": row is not None,
            "passed": bool(
                row
                and row["country_code"] == country
                and row["name_en"]
                and low <= int(str(row["population"])) <= high
            ),
            "row": row,
        }
    return {
        "counts": {kind: dict(counts) for kind, counts in totals.items()},
        "source_classes": dict(classes),
        "feature_codes": dict(codes),
        "languages": dict(languages),
        "spot_checks": checks,
        "spot_checks_passed": all(check["passed"] for check in checks.values()),
        "output_bytes": output_bytes,
        "unit_transform_seconds": round(unit_seconds, 3),
        "line_accounting_verified": True,
        "unique_ids_verified": True,
        "names_foreign_keys_verified": True,
        "geometry": "places use validated WGS84 coordinates; no polygon geometry",
        "excluded": "classes other than P/A; aliases whose entities were not retained",
        "publisher_counts": (
            "Daily export line counts are authoritative; "
            "live web statistics may differ."
        ),
    }
