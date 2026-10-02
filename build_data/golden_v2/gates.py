"""Shared spatial gates and a review receipt tied to measured pilot artifacts."""

from pathlib import Path

from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint
from build_data.cities.common import builder
from build_data.golden.inputs import Inputs, verify_record
from build_data.reconcile.common import Row


def failures(reports: list[Row], named: list[Row]) -> Row:
    return {
        "footprints": [
            f
            for r in reports
            for f in r["footprints"]
            if f["after"]["eligible"] and f["after"]["share"] < 0.99
        ],
        "neighbours": [
            n
            for r in reports
            for n in r["neighbours"]
            if n.get("error")
            or n["point_after"].get("city_id") != n["city_id"]
            or n["polygon_after"]["expected"] < n["polygon_before"]["expected"]
        ],
        "named": [n for n in named if not n["passed"]],
    }


def reviewed(gate: Path, settings: Row, inputs: Inputs, base: Row, ghsl: Row) -> None:
    decision = read_json(gate)
    if (
        not decision.get("accepted")
        or decision.get("builder") != builder()
        or decision.get("policy") != fingerprint(settings)
        or decision.get("inputs") != inputs.identity
        or decision.get("base") != fingerprint(base)
        or decision.get("ghsl") != fingerprint(ghsl)
        or not decision.get("review")
        or decision.get("unresolved_losses", ["missing review"]) != []
    ):
        raise ValueError("Missing, failed or stale reviewed pilot gate")
    for key in ("pilot_summary", "normalization_manifest"):
        verify_record(decision[key])
    summary = read_json(Path(decision["pilot_summary"]["path"]))
    normalized = read_json(Path(decision["normalization_manifest"]["path"]))
    if (
        normalized["builder"] != builder()
        or normalized["policy"] != settings
        or summary["normalization"] != fingerprint(normalized)
        or summary["base"] != fingerprint(base)
    ):
        raise ValueError("Pilot measurements do not match reviewed normalization")
    variant = summary["variants"]["on" if settings["town_radius"]["enabled"] else "off"]
    if not variant["automated_gate"] or set(variant["countries"]) != set(
        settings["pilot"]
    ):
        raise ValueError("Incomplete or failed pilot measures")
    for record in variant["report_artifacts"]:
        verify_record(record)
