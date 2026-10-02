"""All population-15k source points; exact and explicitly supported roll-up credit."""

from collections import Counter

import h3

from build_data.reconcile.common import Row, connect, unpack

from .engine import Engine
from .evaluate import Comparison


def checks(comparison: Comparison, engine: Engine) -> Row:
    db = connect(engine.source, readonly=True)
    try:
        places = [
            unpack(b)
            for (b,) in db.execute(
                "SELECT data FROM geonames WHERE class='P' "
                "AND population>=15000 ORDER BY id"
            )
        ]
    finally:
        db.close()
    cells = [h3.latlng_to_cell(p["latitude"], p["longitude"], 8) for p in places]
    before, after = comparison.query(cells)
    counts: Counter[str] = Counter()
    changes = []
    for p, b, a in zip(places, before, after, strict=True):
        identity = "city:geonames:" + p["source_id"]
        expected = engine.parts.get(identity, identity)
        # Freeze pre-change support: a section inside a baseline containing city.
        # No expected answer is inferred from the new allocation winner.
        if (
            expected == identity
            and p["feature_code"] == "PPLX"
            and b.get("city_method") == "area"
            and identity not in set(engine.ids)
        ):
            expected = b.get("city_id") or identity
        if any(i.startswith("city:country:") for i in engine.ids):
            expected = next(i for i in engine.ids if i.startswith("city:country:"))
        counts["total"] += 1
        for prefix, row in [("before", b), ("after", a)]:
            counts[prefix + "_exact"] += row.get("city_id") == identity
            counts[prefix + "_credited"] += row.get("city_id") == expected
        if b.get("city_id") != a.get("city_id"):
            changes.append(
                {
                    "id": identity,
                    "name": p["name"],
                    "feature_code": p["feature_code"],
                    "population": p["population"],
                    "h3": h3.latlng_to_cell(p["latitude"], p["longitude"], 8),
                    "expected": expected,
                    "before": b,
                    "after": a,
                    "gain": b.get("city_id") != expected
                    and a.get("city_id") == expected,
                    "loss": b.get("city_id") == expected
                    and a.get("city_id") != expected,
                }
            )
    return {"counts": dict(counts), "changes": changes}
