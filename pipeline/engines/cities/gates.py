"""Measured spatial failures and precisely scoped human boundary exceptions."""

from collections.abc import Callable

from pipeline.engines.store.codec import Row


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


def unreviewed(
    losses: list[Row], exceptions: list[Row], origins: Callable[[Row], list[str]]
) -> list[Row]:
    """Credit only individually explained losses with exactly matching evidence.

    Every rebuild renumbers source areas, so a review names the lost boundary by
    its stable upstream origins. `origins` resolves a loss's references, only
    once its city, cells and receiving cities already match a review.
    """
    approved: dict[tuple[str, str], list[Row]] = {}
    for review in exceptions:
        if (
            review.get("reason")
            and review.get("reference")
            and review.get("boundary_origins")
        ):
            key = (review["country"], review["city_id"])
            approved.setdefault(key, []).append(review)
    return [
        loss
        for loss in losses
        if not any(
            matches(loss, review, origins)
            for review in approved.get((loss["country"], loss["city_id"]), [])
        )
    ]


def matches(loss: Row, review: Row, origins: Callable[[Row], list[str]]) -> bool:
    # The report lists lost cells in H3 order; every listed cell is evidence.
    cells = {e["h3"]: str(e["after"]) for e in loss.get("loss_examples", [])}
    return (
        review.get("lost_cells") == loss["lost_cells"]
        and review.get("lost_to") == loss["lost_to"]
        and review.get("cells") == cells
        and sorted(review["boundary_origins"]) == origins(loss)
    )
