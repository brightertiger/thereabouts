"""Final stored-cell quality, canonical foreign keys and completion publication."""

from collections import Counter
from pathlib import Path

import duckdb

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.cities.engine import Engine
from build_data.cities.evaluate import Comparison
from build_data.cities.quality import country_report, named_checks
from build_data.cities.urban import Urban
from build_data.golden.inputs import discover, verify_record
from build_data.golden.metrics import measure
from build_data.golden.reader import Cells
from build_data.reconcile.common import Row

from .gates import failures
from .run import implementation


def reference_checks(tables: list[Row]) -> Row:
    db = duckdb.connect()
    db.execute("SET memory_limit='512MB'")
    db.execute("SET threads=1")
    try:
        for kind in ("places", "canonical_cities", "place_to_city"):
            db.read_parquet(
                [r["path"] for r in tables if r["kind"] == kind]
            ).create_view(kind)
        queries = {
            "unmapped_places": (
                "SELECT count(*) FROM places p "
                "ANTI JOIN place_to_city m USING(place_id)"
            ),
            "dangling_mapping": (
                "SELECT count(*) FROM place_to_city m ANTI JOIN places p "
                "ON m.city_id=p.place_id WHERE m.city_id IS NOT NULL"
            ),
            "dangling_canonical": (
                "SELECT count(*) FROM canonical_cities c ANTI JOIN places p "
                "ON c.city_id=p.place_id"
            ),
            "cross_country_mapping": (
                "SELECT count(*) FROM place_to_city m "
                "JOIN places a ON m.place_id=a.place_id "
                "JOIN places b ON m.city_id=b.place_id "
                "WHERE a.country_code<>b.country_code"
            ),
        }
        result = {}
        for name, query in queries.items():
            row = db.execute(query).fetchone()
            assert row is not None
            result[name] = int(row[0])
        return result
    finally:
        db.close()


def verify(workspace: Workspace, output: Path) -> None:
    manifest = read_json(output / "manifest.json")
    if manifest.get("completed"):
        print("V2 already verified complete", flush=True)
        return
    inputs = discover(workspace)
    for table in manifest["tables"]:
        verify_record(table)
    normalized = manifest["normalization"]
    base = read_json(Path(manifest["base_manifest"]))
    if fingerprint(base) != manifest["base"]:
        raise ValueError("Base snapshot changed before final verification")
    urban = Urban(normalized["ghsl"]["partitions"])
    before, after = Cells(base["tables"]), Cells(manifest["tables"])
    comparison = Comparison(
        before, {}, normalized["policy"]["town_radius"]["enabled"], after
    )
    probes = read_json(Path(__file__).parents[1] / "cities/probes.json")
    ledger = Ledger(workspace.ledger_path)
    digest = fingerprint({"manifest": manifest, "implementation": implementation()})
    totals: Counter[str] = Counter()
    reports = {}
    failed: dict[str, list[Row]] = {"footprints": [], "neighbours": [], "named": []}
    for cc, r in normalized["countries"].items():
        engine = Engine(
            Path(r["index"]["path"]), inputs.paths[cc], urban, normalized["policy"]
        )
        path = output / "quality" / f"{cc}.json"
        unit = str(output.resolve()) + ":" + cc
        if ledger.is_complete("golden-v2.quality", unit, digest):
            report = read_json(path)
        else:
            report = country_report(comparison, cc, engine, urban, probes)
            write_json(path, report)
            ledger.complete("golden-v2.quality", unit, digest, [path])
        totals.update(report["diagnostic"]["counts"])
        for kind, rows_failed in failures([report], []).items():
            failed[kind].extend(rows_failed)
        reports[cc] = str(path)
        write_json(
            workspace.work / "v2-run.json",
            {
                "completed": False,
                "stage": "final country quality",
                "last": cc,
                "countries": len(reports),
                "total_countries": len(normalized["countries"]),
            },
        )
        print("verify v2", cc, report["diagnostic"]["counts"], flush=True)
    cells = [r for r in manifest["tables"] if r["kind"] == "cells"]
    integrity = measure(workspace, manifest["tables"], cells)
    references = reference_checks(manifest["tables"])
    named = named_checks(comparison, inputs)
    failed["named"] = [r for r in named if not r["passed"]]
    rows: Counter[str] = Counter()
    for table in manifest["tables"]:
        rows[table["kind"]] += table["rows"]
    quality = {
        "rows": dict(rows),
        "integrity": integrity,
        "normalization_integrity": references,
        "diagnostic": dict(totals),
        "countries": reports,
        "named": named,
        "failed_spatial_gates": failed,
        "transitions": read_json(output / "transitions.json"),
        "limitations": [
            "GHSL is built-up extent, not municipal authority.",
            "Source-point diagnostic overlaps candidate evidence and is not accuracy.",
            "Unbounded cities and small-town radii have inferred extents.",
        ],
    }
    write_json(output / "quality.json", quality)
    errors = [k for k, v in integrity.items() if k != "represented_r8_centres" and v]
    if errors or any(references.values()) or any(failed.values()):
        raise ValueError(
            f"V2 final gate failed: integrity={errors}, mapping={references}; "
            "inspect failed_spatial_gates"
        )
    licenses = (Path(__file__).parents[1] / "golden/licenses.md").read_text()
    from build_data.acquire.ghsl import ATTRIBUTION, LICENSE_URL

    (output / "DATA_LICENSES.md").write_text(
        licenses + f"\n## GHSL\n\nCC BY 4.0. {ATTRIBUTION}\n\n{LICENSE_URL}\n"
        "WGS84 conversion and city allocation are modifications.\n"
    )
    (output / "DATASET_CARD.md").write_text(
        "# Golden v2\n\nVerified country-checkpointed city normalization "
        "at H3 resolution 8.\n"
        f"{rows['places']:,} places; "
        f"{rows['canonical_cities']:,} absorbing cities/towns; "
        f"{rows['cells']:,} compact cells.\n\n"
        "Country/state/land membership retains the base snapshot. Policy polygons, "
        "accepted city polygons, GHSL urban allocation and optional town radii precede "
        "rural polygons/nearest settlements. Nearest answers beyond 25 km are flagged; "
        "50 km remains the inclusive cutoff.\n\n"
        "See quality.json and quality/<country>.json for regenerated checks, including "
        "failures; these consistency/source checks are not independent accuracy. "
        "Dhaka has an inferred urban allocation, not a verified municipal boundary. "
        "See docs/GOLDEN_V2.md for reproduction and limitations.\n"
    )
    manifest["completed"] = True
    write_json(output / "manifest.json", manifest)
    write_json(
        workspace.work / "v2-run.json",
        {"completed": True, "stage": "verified", "output": str(output)},
    )
