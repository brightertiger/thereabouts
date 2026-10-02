"""Total place-to-city mapping, preserving standalone settlements and null status."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.golden.storage import parquet
from build_data.reconcile.common import Row, connect, encode

from .engine import Engine
from .schemas import MAPPING


def rows(engine: Engine) -> Iterator[Row]:
    db = connect(engine.source, readonly=True)
    canonical = set(engine.ids)
    try:
        # A bounded temporary aggregate avoids a point query per catalogue entity.
        db.execute(
            "CREATE TEMP TABLE anchors AS SELECT entity,min(id) AS id "
            "FROM points GROUP BY entity"
        )
        db.execute("CREATE INDEX temp.anchor_entity ON anchors(entity)")
        cursor = db.execute(
            "SELECT e.id,e.role,p.x,p.y FROM entities e "
            "LEFT JOIN anchors a ON e.id=a.entity "
            "LEFT JOIN points p ON p.id=a.id ORDER BY e.id"
        )
        while batch := cursor.fetchmany(2048):
            located = [(i, r) for i, r in enumerate(batch) if r[2] is not None]
            spatial: dict[int, tuple[str | None, str | None]] = {}
            if located:
                coordinates = np.array(
                    [[r[3], r[2]] for _, r in located], dtype=np.float64
                )
                ids, methods = engine.overlay(
                    coordinates, engine.policy["town_radius"]["enabled"]
                )
                spatial = {
                    i: (city, method)
                    for (i, _), city, method in zip(located, ids, methods, strict=True)
                }
            for i, (identity, role, _, _) in enumerate(batch):
                target, method = spatial.get(i, (None, None))
                if identity in engine.parts:
                    target, method = engine.parts[identity], "policy_part"
                    if any(
                        identity in r.get("identity_aliases", {})
                        for r in engine.policy["countries"].values()
                    ):
                        method = "identity_alias"
                elif identity in canonical:
                    target, method = identity, "self"
                elif role == "city":
                    method = "spatial_absorption" if target else "self"
                    target = target or identity
                else:
                    target, method = None, "non_settlement"
                yield {
                    "place_id": identity,
                    "city_id": target,
                    "method": method,
                    "evidence": encode(
                        {"spatial_rule": spatial.get(i, (None, None))[1]}
                    ),
                }
    finally:
        db.close()


def export(workspace: Workspace, report: Row, engine: Engine) -> Row:
    root = Path(report["index"]["path"]).parent
    path = root / "place_to_city.parquet"
    receipt = root / "mapping.json"
    digest = fingerprint(
        {"country": report["digest"], "radius": engine.policy["town_radius"]["enabled"]}
    )
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete("cities.mapping", report["country"], digest):
        return read_json(receipt)
    table = parquet(path, rows(engine), MAPPING)
    table.update(kind="place_to_city", country=report["country"])
    write_json(receipt, table)
    ledger.complete("cities.mapping", report["country"], digest, [path, receipt])
    return table
