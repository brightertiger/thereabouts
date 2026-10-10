"""Which countries' measured spatial failures stop the stored dataset.

Boundary losses and footprint failures are measured for every country, but only
reviewed countries have human-examined exceptions. With the `reviewed` scope the
other countries' findings are advisory: recorded and counted, never dropped.
Neighbour and named-point failures test human fixtures and always block.
"""

from pipeline.config.quality_policy import SCOPES
from pipeline.engines.store.codec import Row

# Failure kinds measured per country; each finding names its country.
SCOPED = ("all_boundaries", "footprints")


def reviewed_countries(cities: Row, reconcile: Row, review: Row) -> list[str]:
    """Both pilots, countries with a city policy and countries with an exception."""
    return sorted(
        {
            *reconcile["pilot"],
            *cities["pilot"],
            *cities["countries"],
            *(item["country"] for item in review.get("boundary_exceptions") or []),
        }
    )


def scoped(failed: Row, gates: Row) -> tuple[Row, Row]:
    """Split failures into blocking and advisory findings; each lands in one."""
    if gates["blocking_scope"] not in SCOPES:
        raise ValueError(f"Unknown blocking scope: {gates['blocking_scope']}")
    if gates["blocking_scope"] == "all":
        return failed, {kind: [] for kind in SCOPED}
    reviewed = set(gates["reviewed"])
    blocking, advisory = dict(failed), {}
    for kind in SCOPED:
        blocking[kind] = [f for f in failed[kind] if f["country"] in reviewed]
        advisory[kind] = [f for f in failed[kind] if f["country"] not in reviewed]
    return blocking, advisory


def counts(findings: Row) -> dict[str, Row]:
    """Boundary losses, their lost cells and footprint failures by country."""
    result: dict[str, Row] = {}
    for kind in SCOPED:
        for finding in findings[kind]:
            row = result.setdefault(
                finding["country"],
                {"boundary_losses": 0, "lost_cells": 0, "footprint_failures": 0},
            )
            if kind == "footprints":
                row["footprint_failures"] += 1
            else:
                row["boundary_losses"] += 1
                row["lost_cells"] += finding["lost_cells"]
    return dict(sorted(result.items()))


def totals(by_country: dict[str, Row]) -> Row:
    return {
        "countries": len(by_country),
        **{
            key: sum(row[key] for row in by_country.values())
            for key in ("boundary_losses", "lost_cells", "footprint_failures")
        },
    }
