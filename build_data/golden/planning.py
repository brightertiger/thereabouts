"""Conservative country dependencies from all acquired country-area envelopes."""

from __future__ import annotations

import duckdb
import shapely
from shapely import STRtree

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.reconcile.common import Row
from build_data.reconcile.matching import default_perspective

from .inputs import Inputs
from .windows import expanded


def inventory(workspace: Workspace, inputs: Inputs) -> Row:
    path = workspace.work / "golden" / "countries.json"
    digest = fingerprint(
        {
            "sources": inputs.sources,
            "licenses": inputs.policy["compatible_gb_licenses"],
            "perspective": inputs.policy.get("perspective"),
            "plan": 3,
        }
    )
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete("golden.plan", "countries", digest):
        return read_json(path)
    db = duckdb.connect()
    db.execute("SET memory_limit='256MB'")
    db.execute("SET threads=1")
    records: list[tuple[str, float, float, float, float]] = []
    expected: set[str] = set()
    try:
        for source in ("overture", "geoboundaries", "geonames"):
            kind = "places" if source == "geonames" else "areas"
            paths = [
                r["path"]
                for r in inputs.sources[source]["partitions"]
                if r["kind"] == kind
            ]
            db.read_parquet(paths).create_view("parts")
            expected.update(
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT country_code FROM parts "
                    "WHERE country_code IS NOT NULL"
                ).fetchall()
            )
            if kind == "areas":
                condition = (
                    "subtype IN ('country','dependency')"
                    if source == "overture"
                    else "admin_level='ADM0'"
                )
                reader = db.execute(
                    "SELECT country_code,geometry,provenance,license FROM parts "
                    f"WHERE country_code IS NOT NULL AND {condition}"
                ).fetch_record_batch(128)
                for batch in reader:
                    for row in batch.to_pylist():
                        if source == "overture" and not default_perspective(row):
                            continue
                        if (
                            source == "geoboundaries"
                            and row["license"]
                            not in inputs.policy["compatible_gb_licenses"]
                        ):
                            continue
                        shape = shapely.from_wkb(row["geometry"])
                        records.extend(
                            (row["country_code"], *part.bounds)
                            for part in shapely.get_parts(shape)
                        )
    finally:
        db.close()
    value = {"expected": sorted(expected), "bounds": records, "inputs": digest}
    write_json(path, value)
    ledger.complete("golden.plan", "countries", digest, [path])
    return value


class Dependencies:
    def __init__(self, inventory: Row, offshore_m: float) -> None:
        self.identity = fingerprint(
            {"bounds": inventory["bounds"], "offshore_m": offshore_m}
        )
        self.codes = [r[0] for r in inventory["bounds"]]
        self.tree = STRtree([shapely.box(*r[1:]) for r in inventory["bounds"]])
        self.offshore_m = offshore_m

    def countries(self, bounds: tuple[float, float, float, float]) -> list[str]:
        result: set[str] = set()
        for w, e, s, n in expanded(bounds, self.offshore_m):
            result.update(
                self.codes[int(i)] for i in self.tree.query(shapely.box(w, s, e, n))
            )
        return sorted(result)
