"""Group source observations without discarding editions or choosing a first row."""

from collections import defaultdict

from pipeline.engines.serving.snapshot import Row
from pipeline.pack_format.jsonio import canonical
from pipeline.pack_format.layout import (
    CITY_METHOD_MASK,
    CITY_METHODS,
    COUNTRY_AREA,
    OFFSHORE,
    STATE_AREA,
)

from .source import SCHEMES


def common(values: list[object]) -> object:
    return values[0] if all(value == values[0] for value in values) else None


def methods(row: Row) -> Row:
    flags = row["flags"]
    return {
        "city": CITY_METHODS[flags & CITY_METHOD_MASK],
        "state": "area" if flags & STATE_AREA else None,
        "country": "area" if flags & COUNTRY_AREA else None,
        "land": "unknown"
        if row["reference"] is None or row["reference"]["stored_h3"] is None
        else "offshore"
        if flags & OFFSHORE
        else "land",
    }


def group(identity: str, observations: list[Row], family: str, nearest: Row) -> Row:
    observations.sort(
        key=lambda row: (
            *(
                row[field].encode("utf-8")
                for field in ("source", "source_release", "source_id", "golden_table")
            ),
            canonical(row),
        )
    )
    refs = [common([row["refs"][i] for row in observations]) or 0 for i in range(3)]
    evidence = [methods(row) for row in observations]
    aggregate = {
        field: common([row[field] for row in evidence])
        for field in ("country", "state", "city", "land")
    }
    for field, ref in zip(("country", "state", "city"), refs, strict=True):
        if not ref:
            aggregate[field] = None
    aggregate["land"] = aggregate["land"] or "unknown"
    warnings = set()
    if any(row["country_disagrees"] for row in observations):
        warnings.add("source_country_disagrees")
    if any(row["city"] == "rural_nearest_distant" for row in evidence):
        warnings.add("distant_nearest")
    if any(row["city"] in ("urban_allocation", "town_radius") for row in evidence):
        warnings.add("inferred_extent")
    if any(row != evidence[0] for row in evidence[1:]):
        warnings.add("mixed_spatial_methods")
    distance = None
    if aggregate["city"] in ("rural_nearest", "rural_nearest_distant"):
        distant = aggregate["city"] == "rural_nearest_distant"
        distance = {
            "greater_than_m": nearest["distant_m"] if distant else None,
            "at_most_m": nearest["nearest_m"] if distant else nearest["distant_m"],
            "cutoff_m": nearest["nearest_m"],
            "exact_m": None,
        }
    entity = None
    if family == "airports":
        fields = [row["fields"] for row in observations]
        entity = {
            "id": identity,
            "role": "airport",
            **{
                field: common([row[field] for row in fields])
                for field in ("name", "type", "country_code")
            },
            "codes": {
                scheme: common([row[field] for row in fields])
                for scheme, field in SCHEMES.items()
            },
        }
    return {
        "id": identity,
        "entity": entity,
        "refs": refs,
        "methods": aggregate,
        "distance": distance,
        "observations": observations,
        "warnings": sorted(warnings),
    }


def payload(rows: list[tuple[str, Row]], family: str, nearest: Row) -> Row:
    groups: dict[str, list[Row]] = defaultdict(list)
    for identity, observation in rows:
        groups[identity].append(observation)
    return {
        "candidates": [
            group(identity, groups[identity], family, nearest)
            for identity in sorted(groups, key=lambda key: key.encode("utf-8"))
        ]
    }
