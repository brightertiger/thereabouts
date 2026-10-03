"""Stream canonical entities without reinterpreting reconciliation identities."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from pipeline.engines.reconcile.common import Row, connect, encode, unpack


def entities(path: Path, policy: Row) -> Iterator[Row]:
    db = connect(path, readonly=True)
    try:
        country_row = db.execute(
            "SELECT data FROM entities WHERE role='country' ORDER BY id LIMIT 1"
        ).fetchone()
        country_name = unpack(country_row[0])["name"] if country_row else None
        wikidata: dict[str, set[str]] = {}
        for qid, identity in db.execute("SELECT qid,id FROM wikidata"):
            wikidata.setdefault(identity, set()).add(qid)
        for (data,) in db.execute("SELECT data FROM entities ORDER BY id"):
            e = unpack(data)
            sovereign = e["sovereign"] or policy["sovereigns"].get(e["country_code"])
            if not sovereign:
                sovereign = [e["country_code"], country_name]
            qids = set()
            for p in e["provenance"]:
                evidence = p["evidence"]
                qid = evidence.get("upstream", {}).get("wikidata")
                if qid:
                    qids.add(qid)
                if evidence.get("division_provenance"):
                    qid = (
                        json.loads(evidence["division_provenance"])
                        .get("upstream", {})
                        .get("wikidata")
                    )
                    if qid:
                        qids.add(qid)
            if e["geonames_id"]:
                qids.update(wikidata.get(e["geonames_id"], set()))
            yield {
                **{
                    k: e.get(k)
                    for k in (
                        "role",
                        "name",
                        "local_name",
                        "country_code",
                        "code",
                        "code_status",
                        "parent_method",
                        "population",
                        "geonames_id",
                        "geonames_admin1",
                        "feature_code",
                        "source_subtype",
                        "settlement_class",
                        "city_exclusion",
                    )
                },
                "place_id": e["id"],
                "parent_id": e["parent"],
                "name_en": e["name"]
                if e["name_provenance"].get("language") == "en"
                else None,
                "sovereign_id": f"country:{sovereign[0]}",
                "sovereign_code": sovereign[0],
                "sovereign_name": sovereign[1],
                "overture_ids": sorted(
                    s["id"] for s in e["source_ids"] if s["source"] == "overture"
                ),
                "wikidata_ids": sorted(qids),
                **{
                    k: encode(e.get(k))
                    for k in ("source_ids", "provenance", "name_provenance", "link")
                },
            }
    finally:
        db.close()
