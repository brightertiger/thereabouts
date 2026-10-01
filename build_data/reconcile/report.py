"""Render the measured pilot artifacts into the review document."""

from __future__ import annotations

from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json

from .common import Row


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}%"


def render(workspace: Workspace, destination: Path) -> None:
    manifest = read_json(workspace.root / "reconciled" / "manifest.json")
    gate = read_json(workspace.root / "reconciled" / "pilot.json")
    reports = {
        cc: read_json(Path(record["path"]))
        for cc, record in manifest["reports"].items()
    }
    lines = [
        "# Reconciliation pilot",
        "",
        "This report is generated from the committed local reconciliation artifacts. "
        "No H3 table is built. Source acquisition remains unchanged.",
        "",
        f"Policy: `{manifest['policy']['version']}`; builder `{manifest['builder']}`.",
        f"Pilot gate: **{'PASS' if gate['passed'] else 'FAIL'}**. "
        "The gate requires all named checks and at least 99.5% large-place answers.",
        "",
        "## Actual named lookups",
        "",
        "| Point | City | State | Country | Method | Pass |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in gate["named"]:
        a = case["answer"]
        lines.append(
            f"| {case['label']} | {a['city'] or '—'} | {a['state'] or '—'} | "
            f"{a['country']} ({a['country_code']}) | "
            f"{a['city_method']} | {case['passed']} |"
        )
    lines.extend(
        [
            "",
            "French dependencies retain FR/France as sovereign; HK retains CN/China. "
            "SG, MC, HK and the five French territories intentionally have no state.",
            "",
            "## Per-country measurements",
            "",
            "Land coverage is a **spherical-area sampling estimate**, not an "
            "exact polygon-area sum. "
            "Each JSON report includes its 95% Wilson interval and sample count. "
            "Place coverage uses every GeoNames P record and exact polygon predicates.",
            "",
            "| CC | State source / level | Division links | City area links | "
            "Land in city area | Places in city area | Large answer | Country "
            "| State* | City† |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for cc, report in sorted(reports.items()):
        p = report["large_places"]["percentages"]
        state = report["state_policy"]
        values = [
            report["links"]["division_percent"],
            report["links"]["city_area_percent"],
            report["city_land_coverage"]["percent"],
            report["city_place_coverage"]["percent"],
            p["answer"],
            p["country_agrees"],
            p["state_agrees"],
            p["city_same_or_containing"],
        ]
        lines.append(
            f"| {cc} | {state['source'] or 'absent'} / {state['level'] or '—'} | "
            + " | ".join(percent(v) for v in values)
            + " |"
        )
    counts = gate["totals"]
    lines.extend(
        [
            "",
            f"Large-place counts: `{counts}`.",
            "",
            "*State comparison uses GeoNames ADM1 identities, unique ADM1 "
            "names, or the "
            "parent region for province-equivalent states. Unmapped states "
            "count as failures; "
            "intentionally absent states and empty GeoNames admin1 are "
            "excluded from this denominator.",
            "",
            "†City means the same GeoNames identity **or** an assigned city "
            "polygon containing "
            "the point. Containing another city is not independently "
            "adjudicated identity accuracy. "
            "Every class P record with population ≥15,000 remains in the "
            "denominator, including PPLX "
            "and historical places. Reports separate own-identity and "
            "containing-other counts.",
            "",
            "## Largest disagreements",
            "",
            "| Place / GN ID | Population | Actual city, state, country | "
            "Failed comparisons |",
            "| --- | ---: | --- | --- |",
        ]
    )
    failures: list[Row] = []
    for report in reports.values():
        failures.extend(report["large_places"]["failures"])
    for failure in sorted(failures, key=lambda f: -f["population"])[:30]:
        a = failure["answer"]
        failed = ", ".join(
            k for k in ("country", "state", "city") if not failure[k + "_ok"]
        )
        lines.append(
            f"| {failure['name']} / {failure['id']} | {failure['population']:,} | "
            f"{a['city']}, {a['state']}, {a['country_code']} | {failed} |"
        )
    lines.extend(Path(__file__).with_name("report_notes.md").read_text().splitlines())
    lines.append(
        "Published country bytes: "
        f"{sum(r['size'] for r in manifest['countries'].values()):,}; "
        f"land index bytes: {manifest['land']['size']:,}."
    )
    destination.write_text("\n".join(lines), encoding="utf-8")
