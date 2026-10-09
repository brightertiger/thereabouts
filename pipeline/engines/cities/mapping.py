"""Total place-to-city mapping, preserving standalone settlements and null status."""

from collections.abc import Iterator

import numpy as np

from pipeline.engines.store.codec import Row, encode
from pipeline.engines.store.database import connect
from pipeline.engines.store.entities import anchored_entities

from .engine import Engine


def rows(engine: Engine, batch_rows: int) -> Iterator[Row]:
    db = connect(engine.source, readonly=True, cache_kib=engine.limits.sqlite_cache_kib)
    canonical = set(engine.ids)
    try:
        cursor = anchored_entities(db)
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
