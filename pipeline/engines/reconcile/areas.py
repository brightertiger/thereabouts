"""Assign country, state, district and eligible settlement polygons."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pipeline.engines.store.areas import insert_area
from pipeline.engines.store.codec import Row, pack, rows

from .city_identity import footprints
from .classification import (
    CITY_STATE_PRIORITY,
    POLICY_ROLLUP_PRIORITY,
    PROMOTED_ADMIN_PRIORITY,
    area_priority,
    dominated_localities,
)
from .entities import make_entity, save_entity
from .matching import default_perspective, division
from .rollups import selected, targets


def state_policy(root: Path, country: str, policy: Row, batch_rows: int) -> Row:
    if country in policy["no_state"]:
        return {
            "source": None,
            "level": None,
            "reason": "No distinct state under territory/city-state policy",
        }
    selected = dict(policy["states"].get(country, policy["default_state"]))
    if selected["source"] == "overture" and not any(
        r["subtype"] == selected["level"]
        for r in rows(root / "overture_areas.parquet", batch_rows)
    ):
        return {
            "source": "geoboundaries",
            "level": "ADM1",
            "reason": "Overture principal subdivision area layer missing",
        }
    return selected


def _area(
    db: sqlite3.Connection, row: Row, entity: Row, role: str, priority: int = 0
) -> None:
    save_entity(db, entity)
    insert_area(
        db,
        entity["id"],
        role,
        priority,
        row["geometry"],
        tuple(row[k] for k in ("xmin", "ymin", "xmax", "ymax")),
        pack({k: v for k, v in row.items() if k != "geometry"}),
    )


def assign_areas(
    db: sqlite3.Connection,
    root: Path,
    country: str,
    policy: Row,
    state: Row,
    batch_rows: int,
) -> None:
    rollups = targets(db, country, policy)
    dominated = dominated_localities(db, policy)
    city_regions = footprints(db, country, policy)
    rolled: dict[str, set[str]] = {}
    for row in rows(root / "overture_areas.parquet", batch_rows):
        if not default_perspective(row):
            continue
        kind = row["subtype"]
        point, match, link = division(db, row["entity_id"])
        combined = {**(point or {}), **row}
        # Preserve division Wikidata/hierarchy evidence as well as area lineage.
        if point:
            combined["division_provenance"] = point["provenance"]
            combined["name_en"] = row["name_en"] or point["name_en"]
        role = None
        if kind in ("country", "dependency"):
            role = "country"
        elif state["source"] == "overture" and kind == state["level"]:
            role = "state"
        elif (
            state.get("include_direct_region_localities")
            and kind == "locality"
            and point
        ):
            parent = db.execute(
                "SELECT subtype FROM divisions WHERE id=?", (point["parent_source_id"],)
            ).fetchone()
            if parent == ("region",):
                role = "state"
        elif kind in ("county", "localadmin"):
            role = "district"
        if role:
            entity = make_entity(combined, role, country, policy, match, link)
            if role == "state":
                entity["code"] = (
                    row.get("subdivision_code") if kind == "region" else None
                )
            priority = (10 if kind == "dependency" else 0) + int(bool(row["is_land"]))
            _area(db, row, entity, role, priority)
        if kind in ("country", "dependency") and country in policy["city_states"]:
            city = make_entity(combined, "city", country, policy)
            city["id"] = f"city:country:{country}"
            _area(db, row, city, "city", CITY_STATE_PRIORITY)
        elif row["entity_id"] in city_regions:
            _area(
                db, row, city_regions[row["entity_id"]], "city", PROMOTED_ADMIN_PRIORITY
            )
        elif kind in policy["city_subtypes"]:
            target = selected(row, rollups)
            if target:
                _area(db, row, target, "city", POLICY_ROLLUP_PRIORITY)
                rolled.setdefault(target["id"], set()).add(row["entity_id"])
                continue
            # County/localadmin promotion needs shared identity, not its seat's
            # similar name. Localities with no GN link remain explicit evidence.
            city_priority = area_priority(point or combined, match, link, policy)
            if row["entity_id"] in dominated:
                city_priority = None
            if city_priority is not None:
                city = make_entity(combined, "city", country, policy, match, link)
                _area(db, row, city, "city", city_priority)
            elif kind == "locality":
                district = make_entity(
                    combined, "district", country, policy, match, link
                )
                district["city_exclusion"] = (
                    "administrative container of a larger linked settlement"
                    if row["entity_id"] in dominated
                    else "insufficient settlement evidence"
                )
                _area(db, row, district, "district")
    for row in rows(root / "geoboundaries_areas.parquet", batch_rows):
        role = "country" if row["admin_level"] == "ADM0" else None
        if state["source"] == "geoboundaries" and row["admin_level"] == state["level"]:
            role = "state"
        if role:
            if row["license"] not in policy["compatible_gb_licenses"]:
                if role == "state":
                    raise ValueError(
                        f"State fallback licence needs policy review: {row['license']}"
                    )
                continue
            _area(db, row, make_entity(row, role, country, policy), role, -10)
    for rule, target in rollups:
        if len(rolled.get(target["id"], set())) != rule["expected_entities"]:
            raise ValueError(f"Roll-up membership differs from policy: {rule}")
