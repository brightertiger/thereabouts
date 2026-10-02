"""Screen claimed city polygons; retain rejection evidence for rural repair."""

import json
import sqlite3
from collections import defaultdict
from typing import Any

import shapely

from build_data.reconcile.classification import city_order
from build_data.reconcile.common import Row, unpack
from build_data.reconcile.spatial import distance


def screen(
    db: sqlite3.Connection,
    cities: dict[str, Row],
    divisions: dict[str, Row],
    rules: Row,
    fixed: list[Row],
    anchor_edge_m: float = 0.0,
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
            # A territorial locality is a settlement's own source boundary.
            # Its title (including village/hamlet) does not override ownership.
            # Point-only weak seats are absent from cities and get no footprint.
            settlement = division.get("class") in ("city", "town")
            territorial = evidence.get("is_territorial") is True
            if not settlement and not (
                territorial and division.get("class") in ("village", "hamlet")
            ):
                reason = "no territorial settlement boundary evidence"
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
                    "division": division,
                }
            )
    output = list(fixed)
    for identity, parts in grouped.items():
        c = cities[identity]
        geometry = shapely.union_all([p["geometry"] for p in parts])
        anchors = [shapely.Point(c["longitude"], c["latitude"])]
        anchors.extend(
            shapely.Point(d["longitude"], d["latitude"])
            for p in parts
            if (d := p["division"]).get("longitude") is not None
            and d.get("latitude") is not None
        )
        primary_inside = geometry.covers(anchors[0])
        edge = shapely.shortest_line(anchors[0], geometry)
        near_edge = primary_inside or (
            edge is not None
            and distance(*edge.coords[0], *edge.coords[-1]) <= anchor_edge_m
        )
        linked_inside = any(geometry.covers(anchor) for anchor in anchors[1:])
        if not (primary_inside or (near_edge and linked_inside)):
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
                "evidence": {
                    "screen": (
                        "territorial settlement or typed locality; "
                        "contained linked source anchor"
                    )
                },
                "priority": 1,
                "ownership_order": city_order(
                    {
                        "id": identity,
                        "population": c["population"],
                        "geonames_id": identity
                        if identity.startswith("city:geonames:")
                        else None,
                    },
                    max(p["priority"] for p in parts),
                    geometry.area,
                ),
            }
        )
    return output, rejected


def resolve_overlaps(footprints: list[Row]) -> list[Row]:
    """Respect separately retained municipal limits before broader policy unions.

    Retained source precedence resolves shared municipal territory. Store the
    effective footprint plus exclusion IDs; never pretend overlapping input
    geometries were independently validated single-city extents.
    """
    for fp in footprints:
        if fp["method"] == "city_polygon":
            fp["priority"] = -1
    ordered = sorted(footprints, key=footprint_order)
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


def footprint_order(footprint: Row) -> tuple[Any, ...]:
    """Preserve source municipal ownership before smaller unlinked localities."""
    return (
        footprint["priority"],
        *footprint.get(
            "ownership_order", (0, footprint["geometry"].area, 0, footprint["city_id"])
        ),
    )


def roll_up(footprints: list[Row], parts: dict[str, str]) -> list[Row]:
    """Keep accepted part boundaries when their identity rolls into a larger city.

    A built-up policy core can clip a part's edge. Dropping its independently
    accepted locality polygon would let a neighbour take that edge. Preserve the
    same geometry and source precedence, with the owner's requested city name.
    """
    result = []
    for footprint in footprints:
        source = footprint["city_id"]
        if source in parts:
            footprint = {
                **footprint,
                "city_id": parts[source],
                "priority": -1,
                "method": "policy_polygon",
                "evidence": {**footprint["evidence"], "policy_part": source},
            }
        result.append(footprint)
    return result
