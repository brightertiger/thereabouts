"""Country-scoped canonical entities, area assignments and point fallback."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from build_data.acquire import Ledger, Workspace, atomic_output
from build_data.acquire.io import fingerprint, sha256_file

from .checkpoints import complete
from .classification import trusted_city
from .common import Row, check_database, connect, encode, pack, rows
from .entities import (
    add_point,
    create_entities,
    fallback_points,
    make_entity,
    save_entity,
)
from .hierarchy import attach_parents
from .matching import default_perspective, division, link_divisions, prepare_catalog
from .rollups import selected, targets
from .spatial import create_areas, insert_area


def catalog(
    workspace: Workspace, root: Path, country: str, inputs: str, policy: Row
) -> Path:
    digest = fingerprint(
        {
            "inputs": inputs,
            "country": country,
            "code": {
                name: sha256_file(Path(__file__).with_name(name))
                for name in ("common.py", "matching.py", "spatial.py")
            },
            "cutoffs": {k: v for k, v in policy.items() if "match_m" in k},
        }
    )
    output = workspace.work / "reconcile" / digest / f"{country}-links.sqlite"
    ledger = Ledger(workspace.ledger_path)
    if not ledger.is_complete("reconcile.links", country, digest):
        with atomic_output(output, check_database) as temp:
            db = connect(temp)
            try:
                prepare_catalog(db, root)
                link_divisions(db, root, policy)
            finally:
                db.close()
        complete(workspace, "reconcile.links", country, digest, [output])
        print(f"links {country}: complete", flush=True)
    return output


def state_policy(root: Path, country: str, policy: Row) -> Row:
    if country in policy["no_state"]:
        return {
            "source": None,
            "level": None,
            "reason": "No distinct state under territory/city-state policy",
        }
    selected = dict(policy["states"].get(country, policy["default_state"]))
    if selected["source"] == "overture" and not any(
        r["subtype"] == selected["level"] for r in rows(root / "overture_areas.parquet")
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
    db: sqlite3.Connection, root: Path, country: str, policy: Row, state: Row
) -> None:
    rollups = targets(db, country, policy)
    rolled: dict[str, set[str]] = {}
    for row in rows(root / "overture_areas.parquet"):
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
            _area(db, row, city, "city", 100)
        elif kind in policy["city_subtypes"]:
            target = selected(row, rollups)
            if target:
                _area(db, row, target, "city", 50)
                rolled.setdefault(target["id"], set()).add(row["entity_id"])
                continue
            # County/localadmin promotion needs shared identity, not its seat's
            # similar name. Localities with no GN link remain explicit evidence.
            eligible = trusted_city(point or combined, match, link, policy)
            accepted = eligible and (kind == "locality" or link["method"] == "wikidata")
            if accepted or (kind == "locality" and match is None):
                city = make_entity(combined, "city", country, policy, match, link)
                _area(db, row, city, "city")
    for row in rows(root / "geoboundaries_areas.parquet"):
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


def overture_points(db: sqlite3.Connection, country: str, policy: Row) -> None:
    for (source_id,) in db.execute(
        "SELECT id FROM divisions WHERE subtype='locality' ORDER BY id"
    ):
        row, match, link = division(db, source_id)
        assert row is not None
        if not trusted_city(row, match, link, policy):
            continue
        entity = make_entity(row, "city", country, policy, match, link)
        save_entity(db, entity)
        if not match:
            add_point(db, entity["id"], row["longitude"], row["latitude"])
        elif link.get("classification_conflict"):
            add_point(db, entity["id"], match["longitude"], match["latitude"])


def build_country(
    workspace: Workspace,
    root: Path,
    country: str,
    inputs: str,
    policy: Row,
    builder: str,
) -> Path:
    digest = fingerprint(
        {"inputs": inputs, "policy": policy, "builder": builder, "country": country}
    )
    output = workspace.root / "reconciled" / digest / f"{country}.sqlite"
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete("reconcile.country", country, digest):
        return output
    source = catalog(workspace, root, country, inputs, policy)
    state = state_policy(root, country, policy)
    with atomic_output(output, check_database) as temp:
        shutil.copyfile(source, temp)
        db = connect(temp)
        try:
            create_entities(db)
            create_areas(db)
            fallback_points(db, country, policy)
            overture_points(db, country, policy)
            assign_areas(db, root, country, policy, state)
            attach_parents(db, policy)
            db.execute(
                "INSERT INTO metadata VALUES('state_policy',?)", (encode(state),)
            )
            db.execute("INSERT INTO metadata VALUES('policy',?)", (encode(policy),))
            db.commit()
        finally:
            db.close()
    complete(
        workspace,
        "reconcile.country",
        country,
        digest,
        [output],
        metadata={"state_policy": state},
    )
    print(f"country {country}: complete ({output.stat().st_size:,} bytes)", flush=True)
    return output
