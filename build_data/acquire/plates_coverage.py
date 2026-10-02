"""Explicit, narrowly scoped completeness checks against pinned evidence lists."""

from typing import Any

from .plates_config import policy


def reviewed_scopes(
    all_codes: dict[str, dict[str, set[str]]],
    current_codes: dict[str, dict[str, set[str]]],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for country, review in policy("coverage").items():
        baseline = current_codes[country][review["baseline"]]
        comparisons = []
        for other in review.get("comparisons", []):
            pool = current_codes if other["status"] == "current" else all_codes
            observed = pool[country][other["source"]]
            comparisons.append(
                dict(
                    source=other["source"],
                    missing=sorted(baseline - observed),
                    additional=sorted(observed - baseline),
                )
            )
        passed = len(baseline) == review["expected_codes"] and all(
            not comparison["missing"] for comparison in comparisons
        )
        results[country] = dict(
            **review,
            observed_codes=len(baseline),
            status="published_list_complete" if passed else "review_failed",
            comparison_results=comparisons,
            limitation=(
                "This does not establish complete coverage of every national series"
            ),
        )
        if not passed:
            raise ValueError(f"Published plate-list coverage regressed: {country}")
    return results
