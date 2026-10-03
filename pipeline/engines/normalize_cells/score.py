"""Score a golden snapshot against frozen, split-labelled hand-checked points."""

import unicodedata
from collections import Counter

from pipeline.engines.reconcile.common import Row


def normalized_name(value: str | None) -> str:
    return " ".join(unicodedata.normalize("NFC", value or "").casefold().split())


def grade(
    selected: list[dict[str, str]],
    cells: list[str],
    answers: list[Row],
    names: dict[str, Row],
) -> Row:
    counts: Counter[str] = Counter()
    groups: dict[str, Counter[str]] = {}
    rows = []
    for point, cell, answer in zip(selected, cells, answers, strict=True):
        actual = names.get(answer.get("city_id") or "", {})
        expected_id = point.get("expected_city_id") or point.get("expected_place_id")
        expected = (
            point.get("expected_name")
            or point.get("expected_city")
            or point.get("expected_settlement")
        )
        if not expected_id and not expected:
            raise ValueError("Evaluation row needs expected_city_id or expected_city")
        country = point.get("country_code") or point.get("country")
        accepted = {
            normalized_name(n)
            for n in [expected or "", *point.get("accepted_names", "").split("|")]
            if n
        }
        passed = bool(
            (expected_id and answer.get("city_id") == expected_id)
            or (
                point.get("expected_geonames_id")
                and actual.get("geonames_id") == point["expected_geonames_id"]
            )
            or (
                point.get("expected_wikidata")
                and point["expected_wikidata"] in actual.get("wikidata_ids", [])
            )
            or normalized_name(actual.get("name")) in accepted
        )
        passed = passed and (
            not country or answer.get("country_id") == "country:" + country
        )
        if point.get("ambiguous", "").casefold() not in {"yes", "true", "1"}:
            counts["unambiguous_total"] += 1
            counts["unambiguous_correct"] += int(passed)
        group = point.get("category") or point.get("group") or "unspecified"
        counts["total"] += 1
        counts["correct"] += int(passed)
        counts["covered"] += int(bool(answer.get("city_id")))
        counts["distant"] += int(answer.get("city_method") == "rural_nearest_distant")
        group_counts = groups.setdefault(group, Counter())
        group_counts["total"] += 1
        group_counts["correct"] += int(passed)
        rows.append(
            {
                "point": point,
                "h3": cell,
                "answer": {**answer, **actual},
                "passed": passed,
            }
        )
    return {
        "counts": dict(counts),
        "groups": {k: dict(v) for k, v in groups.items()},
        "rows": rows,
    }
