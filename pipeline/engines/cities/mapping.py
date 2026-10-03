"""Total place-to-city mapping, preserving standalone settlements and null status."""

from collections.abc import Iterator

import numpy as np

from pipeline.engines.reconcile.common import Row, connect, encode

from .engine import Engine


def rows(engine: Engine, batch_rows: int) -> Iterator[Row]:
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
        while batch := cursor.fetchmany(batch_rows):
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
