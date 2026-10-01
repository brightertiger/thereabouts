"""Country-scoped canonical entities, area assignments and point fallback."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from build_data.acquire import Ledger, Workspace, atomic_output
from build_data.acquire.io import fingerprint

from .areas import assign_areas, state_policy
from .catalog import catalog
from .checkpoints import complete
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
        assert row is not None
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
    workspace: Workspace,
    root: Path,
    country: str,
    inputs: str,
    policy: Row,
    builder: str,
) -> Path:
    digest, output = country_output(workspace, country, inputs, policy, builder)
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
            ensure_country(db, country, policy)
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


def country_output(
    workspace: Workspace, country: str, inputs: str, policy: Row, builder: str
) -> tuple[str, Path]:
    digest = fingerprint(
        {"inputs": inputs, "policy": policy, "builder": builder, "country": country}
    )
    return digest, workspace.root / "reconciled" / digest / f"{country}.sqlite"
