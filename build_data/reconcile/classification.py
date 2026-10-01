"""Resolve explicit settlement classifications without admitting neighborhoods."""

from .common import Row


def trusted_city(row: Row, match: Row | None, link: Row, policy: Row) -> bool:
    if row["subtype"] in policy["excluded_subtypes"]:
        return False
    if match is None:
        return bool(row["subtype"] == "locality")
    if match["feature_code"] in policy["settlement_codes"]:
        return True
    if (
        match["feature_code"] == "PPLX"
        and row["subtype"] == "locality"
        and row.get("feature_class") in policy["trusted_city_classes"]
        and link["method"] == "wikidata"
    ):
        link["classification_conflict"] = (
            "GeoNames PPLX; shared Wikidata identity and explicit Overture city class"
        )
        return True
    return False
