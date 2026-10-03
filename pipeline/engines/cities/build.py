"""Atomic, input-keyed country normalization without modifying reconciliation."""

from pathlib import Path

import shapely

from pipeline.config.engines import EngineLimits
from pipeline.engines.reconcile.common import Row, check_database, connect, encode, pack
from pipeline.engines.storage import file_record, parquet
from pipeline.runtime.jsonio import atomic_output, write_json

from .candidates import candidates, divisions
from .footprints import resolve_overlaps, roll_up, screen
from .policy_areas import policy_areas
from .schemas import CITIES
from .urban import Urban


def build_country(
    workspace: Path,
    root: Path,
    cc: str,
    source: Path,
    urban: Urban,
    policy: Row,
    inputs_hash: str,
    limits: EngineLimits,
) -> Row:
    report_path = root / "report.json"
    db = connect(source, readonly=True, cache_kib=limits.sqlite_cache_kib)
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
        footprints, rejected = screen(
            db, cities, evidence, rules, fixed, policy["boundary_anchor_edge_m"]
        )
        original_boundaries = [dict(f) for f in footprints]
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
        footprints = roll_up(footprints, parts)
        footprints = [f for f in footprints if f["city_id"] in cities]
        footprints = resolve_overlaps(footprints)
        missing_targets = set(parts.values()) - cities.keys()
        if missing_targets:
            raise ValueError(f"Unresolved policy targets: {missing_targets}")
    finally:
        db.close()
    path = root / "index.sqlite"
    with atomic_output(path) as temporary:
        out = connect(temporary, cache_kib=limits.sqlite_cache_kib)
        try:
            out.executescript("""
                CREATE TABLE cities(id TEXT PRIMARY KEY,data BLOB);
                CREATE TABLE footprints(id INTEGER PRIMARY KEY,city_id TEXT,
                  geometry BLOB,data BLOB);
                CREATE TABLE parts(place_id TEXT PRIMARY KEY,city_id TEXT);
                CREATE TABLE boundaries(id INTEGER PRIMARY KEY,city_id TEXT,
                  geometry BLOB,data BLOB);
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
            for i, boundary in enumerate(original_boundaries):
                identity = boundary["city_id"]
                metadata = {k: v for k, v in boundary.items() if k != "geometry"}
                metadata["target_id"] = parts.get(identity, identity)
                out.execute(
                    "INSERT INTO boundaries VALUES(?,?,?,?)",
                    (i, identity, boundary["geometry"].wkb, pack(metadata)),
                )
            out.commit()
        finally:
            out.close()
        check_database(temporary)
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
    table = parquet(
        workspace,
        root / "canonical_cities.parquet",
        rows,
        CITIES,
        limits.parquet_batch_rows,
    )
    table.update(kind="canonical_cities", country=cc)
    report: Row = {
        "country": cc,
        "digest": inputs_hash,
        "index": file_record(workspace, path),
        "table": table,
        "candidates": len(cities),
        "footprints": len(footprints),
        "policy_parts": len(parts),
        "eligibility_counts": counts,
        "rejected_areas": rejected,
    }
    write_json(report_path, report)
    print(
        f"normalize {cc}: {len(cities)} cities/towns, "
        f"{len(footprints)} footprints, {len(rejected)} rejected areas",
        flush=True,
    )
    return report
