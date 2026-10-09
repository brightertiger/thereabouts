"""Explicit reviewed source membership; country names never enter algorithm code."""

import sqlite3

import shapely
from shapely.geometry.base import BaseGeometry

from pipeline.engines.store.areas import areas_by_role, entity_areas
from pipeline.engines.store.codec import Row, unpack

from .urban import Urban


def policy_areas(
    db: sqlite3.Connection, cities: dict[str, Row], rules: Row, urban: Urban
) -> list[Row]:
    output = []
    for rule in rules.get("footprints", []):
        target = rule["city_id"]
        if target not in cities:
            raise ValueError(f"Policy target has no canonical anchor: {target}")
        pieces: list[BaseGeometry] = []
        refs: list[str] = []
        if rule.get("members"):
            members = set(rule["members"])
            found = set()
            for area, _, _, blob, evidence in areas_by_role(db):
                source = unpack(evidence).get("entity_id")
                if source in members:
                    found.add(source)
                    pieces.append(shapely.from_wkb(blob))
                    refs.append(str(area))
            if found != members:
                raise ValueError(f"Missing pinned policy members: {members - found}")
        else:
            role = rule.get("role", "city")
            for area_entity in rule.get(
                "area_entities", [rule.get("area_entity", target)]
            ):
                found_rows = list(
                    entity_areas(db, area_entity, role, rule.get("priority"))
                )
                if not found_rows:
                    raise ValueError(f"Missing policy area identity: {area_entity}")
                for area, blob in found_rows:
                    pieces.append(shapely.from_wkb(blob))
                    refs.append(str(area))
        if not pieces:
            raise ValueError(f"No source footprint for {target}")
        geometry = shapely.union_all(pieces)
        if rule.get("clip_urban"):
            c = cities[target]
            geometry = geometry.intersection(urban.at(c["longitude"], c["latitude"]))
        if not geometry.is_valid or geometry.is_empty:
            raise ValueError(f"Invalid policy footprint: {target}")
        output.append(
            {
                "city_id": target,
                "geometry": geometry,
                "method": "policy_polygon",
                "references": refs,
                "evidence": rule,
                "priority": 0,
            }
        )
    return output
