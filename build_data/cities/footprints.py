"""Screen claimed city polygons; retain rejection evidence for rural repair."""

import json
import sqlite3
from collections import defaultdict

import shapely

from build_data.reconcile.common import Row, unpack


def screen(
    db: sqlite3.Connection,
    cities: dict[str, Row],
    divisions: dict[str, Row],
    rules: Row,
    fixed: list[Row],
) -> tuple[list[Row], list[Row]]:
    fixed_ids = {r["city_id"] for r in fixed}
    grouped: dict[str, list[Row]] = defaultdict(list)
    rejected = []
    for area, identity, priority, blob, data in db.execute(
        "SELECT id,entity,priority,geometry,evidence FROM areas "
        "WHERE role='city' ORDER BY id"
    ):
        identity = rules.get("identity_aliases", {}).get(identity, identity)
        evidence = unpack(data)
        reason = None
        division = divisions.get(evidence.get("entity_id", ""), {})
        upstream = json.loads(evidence.get("provenance", "{}"))
        if identity in fixed_ids:
            reason = "replaced by approved policy footprint"
        elif evidence.get("entity_id") in rules.get("excluded_areas", []):
            reason = "excluded by country policy"
        elif evidence.get("subtype") != "locality":
            reason = "administrative container; no municipal policy approval"
        elif identity in cities:
            if division.get("class") in ("village", "hamlet") and not set(
                cities[identity]["classes"]
            ) & {"city", "town"}:
                # A large village can be an urban anchor without making its
                # existing rural village boundary invalid. Keep that fallback.
                continue
            if division.get("class") not in ("city", "town"):
                reason = "polygon division is not typed city/town"
            elif any(
                term.casefold() in json.dumps(upstream, ensure_ascii=False).casefold()
                for term in rules.get("container_terms", [])
            ):
                reason = "source names identify an administrative container"
        if reason:
            rejected.append({"area_id": area, "city_id": identity, "reason": reason})
        elif identity in cities:
            grouped[identity].append(
                {
                    "area_id": area,
                    "geometry": shapely.from_wkb(blob),
                    "evidence": evidence,
                    "priority": priority,
                }
            )
    output = list(fixed)
    for identity, parts in grouped.items():
        c = cities[identity]
        geometry = shapely.union_all([p["geometry"] for p in parts])
        if not geometry.covers(shapely.Point(c["longitude"], c["latitude"])):
            rejected.extend(
                {
                    "area_id": p["area_id"],
                    "city_id": identity,
                    "reason": "anchor outside claimed boundary",
                }
                for p in parts
            )
            continue
        output.append(
            {
                "city_id": identity,
                "geometry": geometry,
                "method": "city_polygon",
                "references": [str(p["area_id"]) for p in parts],
                "evidence": {"screen": "typed locality and contained anchor"},
                "priority": 1,
            }
        )
    return output, rejected


def resolve_overlaps(footprints: list[Row]) -> list[Row]:
    """Respect separately retained municipal limits before broader policy unions.

    Smaller municipal boundaries win shared source territory. Store the effective
    footprint plus explicit exclusion IDs; never pretend overlapping input
    geometries were independently validated single-city extents.
    """
    for fp in footprints:
        if fp["method"] == "city_polygon":
            fp["priority"] = -1
    ordered = sorted(
        footprints, key=lambda fp: (fp["priority"], fp["geometry"].area, fp["city_id"])
    )
    tree = shapely.STRtree([fp["geometry"] for fp in ordered])
    result = []
    for i, fp in enumerate(ordered):
        earlier = [
            ordered[int(j)]
            for j in tree.query(fp["geometry"], predicate="intersects")
            if int(j) < i and ordered[int(j)]["city_id"] != fp["city_id"]
        ]
        if earlier:
            fp = dict(fp)
            fp["evidence"] = {
                **fp["evidence"],
                "independent_boundary_exclusions": sorted(
                    {e["city_id"] for e in earlier}
                ),
                "original_area_degrees2": fp["geometry"].area,
            }
            fp["geometry"] = fp["geometry"].difference(
                shapely.union_all([e["geometry"] for e in earlier])
            )
        if not fp["geometry"].is_empty:
            result.append(fp)
    return result
