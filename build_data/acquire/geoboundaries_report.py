"""Geoboundaries report."""

from __future__ import annotations

from typing import Any

from .geoboundaries_settings import KINDS


def _summary(
    inventory: dict[str, Any], reports: list[dict[str, Any]], failed: dict[str, str]
) -> dict[str, Any]:
    by_unit = {str(report["unit_id"]): report for report in reports}
    gbr = by_unit.get("GBR-ADM1")
    usa = by_unit.get("USA-ADM1")
    gbr_names = {"England", "Scotland", "Wales", "Northern Ireland"}
    usa_nonstates = {
        "District of Columbia",
        "Puerto Rico",
        "American Samoa",
        "Guam",
        "United States Virgin Islands",
        "Commonwealth of the Northern Mariana Islands",
    }
    usa_names = set(usa["feature_names"]) if usa else set()
    counts: dict[str, dict[str, int]] = {}
    for level in KINDS:
        selected = [
            report for report in reports if str(report["unit_id"]).endswith(level)
        ]
        counts[level] = {
            "countries": len(selected),
            "features": sum(int(r["input_features"]) for r in selected),
            "rows": sum(int(r["output_rows"]) for r in selected),
        }
    return {
        "source_release": inventory["source_release"],
        "layers": len(reports),
        "by_level": counts,
        "failed": failed,
        "missing_in_api": inventory["missing_in_api"],
        "input_features": sum(int(r["input_features"]) for r in reports),
        "output_rows": sum(int(r["output_rows"]) for r in reports),
        "parquet_bytes": sum(int(r["parquet_bytes"]) for r in reports),
        "partitions": sum(int(r["partitions"]) for r in reports),
        "unit_processing_seconds": sum(
            float(r.get("elapsed_seconds", 0)) for r in reports
        ),
        "invalid_input": sum(int(r["invalid_input"]) for r in reports),
        "repaired_features": sum(int(r["repaired_features"]) for r in reports),
        "split_features": sum(int(r["split_features"]) for r in reports),
        "output_invalid_geometries": 0,
        "inventory_corrections": inventory.get("inventory_corrections", []),
        "coverage_reference": inventory.get("coverage_reference"),
        "publisher_count_discrepancies": {
            r["unit_id"]: r["count_discrepancy"]
            for r in reports
            if "count_discrepancy" in r
        },
        "reject_count": sum(int(r["reject_count"]) for r in reports),
        "spot_checks": {
            "GBR_ADM1": {
                "passed": gbr is not None and set(gbr["feature_names"]) == gbr_names,
                "names": gbr["feature_names"] if gbr else None,
            },
            "USA_ADM1": {
                "passed": usa is not None
                and usa["input_features"] == usa["published_feature_count"]
                and usa["input_features"] == 56
                and len(usa_names) == 56
                and usa_nonstates <= usa_names,
                "count": usa["input_features"] if usa else None,
                "published_count": usa["published_feature_count"] if usa else None,
                "expected_count": 56,
                "state_count": len(usa_names - usa_nonstates),
                "district_and_territory_names": sorted(usa_names & usa_nonstates),
                "expected_composition": "50 states, DC, five inhabited territories",
                "names": usa["feature_names"] if usa else None,
            },
        },
        "dropped_policy_rows": 0,
        "english_names_inferred": 0,
    }
