"""Shared spatial gates and a review receipt tied to measured pilot artifacts."""

from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint
from build_data.cities.common import builder
from build_data.golden import paths as data_paths
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
        "all_boundaries": [
            b for r in reports for b in r.get("all_boundaries", []) if b["lost_cells"]
        ],
    }


def reviewed(
    gate: Path, settings: Row, inputs: Inputs, base: Row, ghsl: Row, *, root: Path
) -> None:
    decision = data_paths.read(gate, root)
    if (
        not decision.get("accepted")
        or decision.get("builder") != builder()
        or decision.get("policy") != fingerprint(settings)
        or decision.get("inputs") != inputs.identity
        or decision.get("base") != data_paths.digest(base, root)
        or decision.get("ghsl") != data_paths.digest(ghsl, root)
        or not decision.get("review")
        or decision.get("unresolved_losses", ["missing review"]) != []
    ):
        raise ValueError("Missing, failed or stale reviewed pilot gate")
    if "development" in decision:
        verify_record(decision["development"])
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
    if unreviewed(
        variant.get("boundary_losses", []), decision.get("boundary_exceptions", [])
    ):
        raise ValueError("Unexamined accepted-boundary losses in pilot")
    for record in variant["report_artifacts"]:
        verify_record(record)


def unreviewed(losses: list[Row], exceptions: list[Row]) -> list[Row]:
    """Credit only individually explained losses with exactly matching evidence."""
    approved: dict[tuple[str, str], list[Row]] = {}
    for review in exceptions:
        if review.get("reason") and review.get("reference"):
            key = (review["country"], review["city_id"])
            approved.setdefault(key, []).append(review)
    return [
        loss
        for loss in losses
        if not any(
            review.get("lost_cells") == loss["lost_cells"]
            and review.get("lost_to") == loss["lost_to"]
            and (
                "boundary_references" not in review
                or review["boundary_references"] == loss.get("references")
            )
            for review in approved.get((loss["country"], loss["city_id"]), [])
        )
    ]


def record(workspace: Workspace, notes: Path, destination: Path) -> None:
    """Bind a human pilot review to current artifacts; this never changes city rules."""
    from build_data.acquire.artifacts import file_record
    from build_data.acquire.manifests import load_manifest
    from build_data.cities.common import policy
    from build_data.golden.inputs import discover

    from .base import load

    inputs = discover(workspace)
    settings = policy()
    _, base = load(workspace, inputs)
    review = read_json(notes)
    if not review.get("accepted") or not review.get("review"):
        raise ValueError("Pilot needs an explicit reasoned review")
    summary_path = workspace.work / "v2-pilot/summary.json"
    normalized_path = workspace.root / "city_normalized/manifest.json"
    development_path = workspace.work / "v2-dev.json"
    development = read_json(development_path)
    variant = "on" if settings["town_radius"]["enabled"] else "off"
    minimum = review["minimum_dev_correct"]
    if development[variant]["after"]["counts"]["correct"] < minimum:
        raise ValueError("Development score is below the reviewed minimum")
    decision = {
        **review,
        "builder": builder(),
        "policy": fingerprint(settings),
        "inputs": inputs.identity,
        "base": data_paths.digest(base, workspace.root),
        "ghsl": data_paths.digest(load_manifest(workspace, "ghsl"), workspace.root),
        "pilot_summary": file_record(summary_path),
        "normalization_manifest": file_record(normalized_path),
        "development": file_record(development_path),
    }
    # Validate a temporary receipt before replacing the previously reviewed gate.
    temporary = destination.with_suffix(".review.json")
    data_paths.write(temporary, decision, workspace.root)
    reviewed(
        temporary,
        settings,
        inputs,
        base,
        load_manifest(workspace, "ghsl"),
        root=workspace.root,
    )
    temporary.replace(destination)
