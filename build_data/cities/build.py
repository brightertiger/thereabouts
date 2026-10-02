"""Atomic, input-keyed country normalization without modifying reconciliation."""

from pathlib import Path

import shapely

from build_data.acquire import Ledger, Workspace, atomic_output
from build_data.acquire.artifacts import file_record, read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.golden.storage import parquet
from build_data.reconcile.common import Row, check_database, connect, encode, pack

from .candidates import candidates, divisions
from .common import builder
from .footprints import resolve_overlaps, screen
from .policy_areas import policy_areas
from .schemas import CITIES
from .urban import Urban


def build_country(
    workspace: Workspace, cc: str, source: Row, urban: Urban, ghsl: Row, policy: Row
) -> Row:
    digest = fingerprint(
        {"country": source, "ghsl": ghsl, "policy": policy, "builder": builder()}
    )
    root = workspace.root / "city_normalized" / digest / cc
    report_path = root / "report.json"
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete("cities.country", cc, digest):
        return read_json(report_path)
    db = connect(Path(source["path"]), readonly=True)
    rules = policy["countries"].get(cc, {})
    try:
        evidence = divisions(db)
        cities, counts = candidates(db, cc, policy["eligibility"], rules, evidence)
        fixed = policy_areas(db, cities, rules, urban)
        # Existing city-state conventions are explicit source policy areas.
        for identity in cities:
            if identity.startswith("city:country:"):
                shapes = [
                    shapely.from_wkb(b)
                    for (b,) in db.execute(
                        "SELECT geometry FROM areas WHERE entity=? AND role='city'",
                        (identity,),
                    )
                ]
                if shapes:
                    fixed.append(
                        {
                            "city_id": identity,
                            "geometry": shapely.union_all(shapes),
                            "method": "policy_polygon",
                            "priority": 0,
                            "references": [identity],
                            "evidence": {"city_state": cc},
                        }
                    )
        footprints, rejected = screen(db, cities, evidence, rules, fixed)
        parts = {**rules.get("parts", {}), **rules.get("identity_aliases", {})}
        independent = set(rules.get("independent", []))
        for fp in footprints:
            if fp["city_id"] in independent:
                fp["priority"] = -1
        # Only approved policy footprints absorb other canonical anchors wholesale.
        # Uncertain generic overlaps remain distinct and are measured by probes.
        for identity, c in cities.items():
            if identity in independent or identity in {r["city_id"] for r in fixed}:
                continue
            point = shapely.Point(c["longitude"], c["latitude"])
            containing = [f for f in fixed if f["geometry"].covers(point)]
            if containing:
                parts[identity] = min(containing, key=lambda f: f["geometry"].area)[
                    "city_id"
                ]
        for fp in fixed:
            members = set(fp["evidence"].get("members", []))
            for member in members:
                d = evidence[member]
                parts["district:overture:" + member] = fp["city_id"]
                if d["link"]:
                    parts["city:geonames:" + d["link"]] = fp["city_id"]
                parts["city:overture:" + member] = fp["city_id"]
        for identity in list(parts):
            target = parts[identity]
            seen = {identity}
            while target in parts and parts[target] != target:
                if target in seen:
                    raise ValueError("Spatial/policy roll-up cycle")
                seen.add(target)
                target = parts[target]
            if identity == target:
                del parts[identity]
            else:
                parts[identity] = target
                cities.pop(identity, None)
        footprints = [f for f in footprints if f["city_id"] in cities]
        footprints = resolve_overlaps(footprints)
        missing_targets = set(parts.values()) - cities.keys()
        if missing_targets:
            raise ValueError(f"Unresolved policy targets: {missing_targets}")
    finally:
        db.close()
    path = root / "index.sqlite"
    with atomic_output(path, check_database) as temporary:
        out = connect(temporary)
        try:
            out.executescript("""
                CREATE TABLE cities(id TEXT PRIMARY KEY,data BLOB);
                CREATE TABLE footprints(id INTEGER PRIMARY KEY,city_id TEXT,
                  geometry BLOB,data BLOB);
                CREATE TABLE parts(place_id TEXT PRIMARY KEY,city_id TEXT);
                CREATE TABLE rejected(area_id INTEGER PRIMARY KEY,
                  city_id TEXT,reason TEXT);
            """)
            out.executemany(
                "INSERT INTO cities VALUES(?,?)",
                [(k, pack(v)) for k, v in sorted(cities.items())],
            )
            out.executemany("INSERT INTO parts VALUES(?,?)", sorted(parts.items()))
            out.executemany(
                "INSERT INTO rejected VALUES(:area_id,:city_id,:reason)", rejected
            )
            for i, fp in enumerate(footprints):
                out.execute(
                    "INSERT INTO footprints VALUES(?,?,?,?)",
                    (
                        i,
                        fp["city_id"],
                        fp["geometry"].wkb,
                        pack({k: v for k, v in fp.items() if k != "geometry"}),
                    ),
                )
            out.commit()
        finally:
            out.close()
    rows = []
    for identity, c in sorted(cities.items()):
        refs = [
            {"method": f["method"], "sources": f["references"]}
            for f in footprints
            if f["city_id"] == identity
        ]
        rows.append(
            {
                **c,
                "source_ids": encode(c["source_ids"]),
                "footprint_references": encode(refs),
                "allocation_rule": "bounded"
                if refs
                else "urban_allocation; optional town_radius",
            }
        )
    table = parquet(root / "canonical_cities.parquet", rows, CITIES)
    table.update(kind="canonical_cities", country=cc)
    report: Row = {
        "country": cc,
        "digest": digest,
        "index": file_record(path),
        "table": table,
        "candidates": len(cities),
        "footprints": len(footprints),
        "policy_parts": len(parts),
        "eligibility_counts": counts,
        "rejected_areas": rejected,
    }
    write_json(report_path, report)
    ledger.complete(
        "cities.country", cc, digest, [path, Path(table["path"]), report_path]
    )
    print(
        f"normalize {cc}: {len(cities)} cities/towns, "
        f"{len(footprints)} footprints, {len(rejected)} rejected areas",
        flush=True,
    )
    return report
