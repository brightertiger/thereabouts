"""Country-scoped canonical entities, area assignments and point fallback."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from pipeline.config.engines import EngineLimits
from pipeline.runtime.jsonio import atomic_output

from .areas import assign_areas, state_policy
from .classification import trusted_city
from .common import Row, check_database, connect, encode
from .entities import (
    add_point,
    create_entities,
    ensure_country,
    fallback_points,
    make_entity,
    save_entity,
)
from .hierarchy import attach_parents
from .matching import division
from .spatial import create_areas


def overture_points(db: sqlite3.Connection, country: str, policy: Row) -> None:
    for (source_id,) in db.execute(
        "SELECT id FROM divisions WHERE subtype='locality' ORDER BY id"
    ):
        row, match, link = division(db, source_id)
        if row is None:
            raise ValueError(f"Missing source division: {source_id}")
        if not trusted_city(row, match, link, policy):
            value = make_entity(row, "district", country, policy, match, link)
            value["city_exclusion"] = "insufficient settlement evidence"
            save_entity(db, value)
            continue
        entity = make_entity(row, "city", country, policy, match, link)
        save_entity(db, entity)
        if not match:
            add_point(db, entity["id"], row["longitude"], row["latitude"])
        elif link.get("classification_conflict"):
            add_point(db, entity["id"], match["longitude"], match["latitude"])


def build_country(
    source: Path,
    root: Path,
    output: Path,
    country: str,
    policy: Row,
    limits: EngineLimits,
) -> Path:
    state = state_policy(root, country, policy)
    with atomic_output(output) as temp:
        shutil.copyfile(source, temp)
        db = connect(temp, cache_kib=limits.sqlite_cache_kib)
        try:
            create_entities(db)
            create_areas(db)
            fallback_points(db, country, policy)
            overture_points(db, country, policy)
            assign_areas(db, root, country, policy, state)
            ensure_country(db, country, policy)
            attach_parents(db, policy, limits.state_vote_batch_rows)
            db.execute(
                "INSERT INTO metadata VALUES('state_policy',?)", (encode(state),)
            )
            db.execute("INSERT INTO metadata VALUES('policy',?)", (encode(policy),))
            db.commit()
        finally:
            db.close()
        check_database(temp)
    return output
