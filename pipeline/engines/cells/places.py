"""Stream canonical entities without reinterpreting reconciliation identities."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from pipeline.engines.store.catalog import wikidata_links
from pipeline.engines.store.codec import Row, encode
from pipeline.engines.store.database import connect
from pipeline.engines.store.entities import country_entity
from pipeline.engines.store.entities import entities as canonical


def entities(path: Path, policy: Row, cache_kib: int) -> Iterator[Row]:
    db = connect(path, readonly=True, cache_kib=cache_kib)
    try:
        country = country_entity(db)
        country_name = country["name"] if country else None
        wikidata: dict[str, set[str]] = {}
        for qid, identity in wikidata_links(db):
            wikidata.setdefault(identity, set()).add(qid)
        for value in canonical(db):
            e = cast(Row, value)
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
