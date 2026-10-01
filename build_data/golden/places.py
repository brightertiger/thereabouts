"""Stream canonical entities without reinterpreting reconciliation identities."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from build_data.acquire import Ledger, Workspace
from build_data.acquire.io import fingerprint
from build_data.acquire.ledger import read_units
from build_data.reconcile.common import Row, connect, encode, unpack

from .inputs import Inputs
from .schemas import PLACES
from .storage import budget, parquet


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


def export(workspace: Workspace, inputs: Inputs) -> list[Row]:
    ledger = Ledger(workspace.ledger_path)
    saved = {
        r["unit_id"]: r for r in read_units(workspace.ledger_path, "golden.places")
    }
    output = []
    for cc, record in sorted(inputs.countries.items()):
        digest = fingerprint({"country": record, "places": 2, "policy": inputs.policy})
        if ledger.is_complete("golden.places", cc, digest):
            output.append(saved[cc]["metadata"]["table"])
            continue
        budget(workspace, required=256_000_000)
        path = workspace.root / "golden" / "places" / f"{cc}.parquet"
        table = parquet(path, entities(Path(record["path"]), inputs.policy), PLACES)
        table.update(country=cc, kind="places")
        ledger.complete("golden.places", cc, digest, [path], metadata={"table": table})
        output.append(table)
        print(f"places {cc}: {table['rows']:,}", flush=True)
    return output
