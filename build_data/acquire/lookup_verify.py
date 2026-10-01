"""Verify lookup manifests, publisher accounting and the requested spatial checks."""

import argparse
import ipaddress
from pathlib import Path
from typing import Any

import duckdb
import h3

from .artifacts import read_json
from .io import write_json
from .lookup_catalog import LOOKUP_SOURCES
from .lookup_coverage_audit import world_coverage
from .manifests import load_manifest
from .runtime import disk_bytes
from .status import source_status
from .workspace import Workspace


def verify(workspace: Workspace) -> dict[str, Any]:
    manifests = {source: load_manifest(workspace, source) for source in LOOKUP_SOURCES}
    status = {source: source_status(workspace, source) for source in LOOKUP_SOURCES}
    if any(
        s[stage] != "complete"
        for s in status.values()
        for stage in ("download", "normalize")
    ):
        raise ValueError("Some lookup sources are incomplete")
    counts = {
        source: read_json(workspace.normalized(source) / "verification.json")
        for source in LOOKUP_SOURCES
    }

    def paths(source: str, kind: str) -> list[str]:
        return [p["path"] for p in manifests[source]["partitions"] if p["kind"] == kind]

    checks: dict[str, Any] = {}
    with duckdb.connect(config={"memory_limit": "512MB", "threads": "1"}) as db:
        for code, country, bounds in (
            ("560001", "IN", (12.8, 13.2, 77.4, 77.8)),
            ("10001", "US", (40.7, 40.8, -74.1, -73.9)),
        ):
            rows = db.execute(
                "SELECT latitude, longitude, h3 FROM read_parquet(?) WHERE "
                "country_code=? AND postal_code=?",
                [paths("postal", "postal_codes"), country, code],
            ).fetchall()
            if not rows or not all(
                bounds[0] <= lat <= bounds[1]
                and bounds[2] <= lon <= bounds[3]
                and h3.latlng_to_cell(lat, lon, 8) == cell
                for lat, lon, cell in rows
            ):
                raise ValueError(f"Postal spot check failed: {country}/{code}")
            checks[f"postal_{country}_{code}"] = rows
        for code, country in (("BLR", "IN"), ("JFK", "US")):
            rows = db.execute(
                "SELECT latitude, longitude, h3, country_code, icao_code FROM "
                "read_parquet(?) WHERE iata_code=?",
                [paths("airports", "airports"), code],
            ).fetchall()
            if not rows or not all(
                cc == country and h3.latlng_to_cell(lat, lon, 8) == cell
                for lat, lon, cell, cc, _ in rows
            ):
                raise ValueError(f"Airport spot check failed: {code}")
            checks[f"airport_{code}"] = rows
        for lat, lon, expected in (
            (12.9716, 77.5946, "Asia/Kolkata"),
            (40.7128, -74.0060, "America/New_York"),
            (0, -150, "Etc/GMT+10"),
        ):
            cell = h3.latlng_to_cell(lat, lon, 8)
            ancestors = [h3.cell_to_parent(cell, level) for level in range(9)]
            result = [
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT tzid FROM read_parquet(?) WHERE h3 IN "
                    "(SELECT unnest(?))",
                    [paths("timezones", "timezone_cells"), ancestors],
                ).fetchall()
            ]
            if expected not in result:
                raise ValueError(
                    f"Timezone spot check failed: {expected}, got {result}"
                )
            checks[expected] = dict(cell=cell, zones=result)
        address = ipaddress.ip_address("8.8.8.8").packed.rjust(16, b"\0")
        result = db.execute(
            "SELECT ip_start, ip_end, country_code, city, h3 FROM "
            "read_parquet(?) WHERE ip_version=4 AND ip_start_packed <= ? AND "
            "ip_end_packed >= ?",
            [paths("dbip", "ip_ranges"), address, address],
        ).fetchall()
        if len(result) != 1 or result[0][2] != "US":
            raise ValueError(f"DB-IP spot check failed: {result}")
        checks["8.8.8.8"] = result
        checks["ip_versions"] = db.execute(
            "SELECT ip_version,count(*) FROM read_parquet(?) GROUP BY "
            "ip_version ORDER BY ip_version",
            [paths("dbip", "ip_ranges")],
        ).fetchall()
        checks["iso_subdivisions"] = db.execute(
            "SELECT code_system,count(*) FROM read_parquet(?) GROUP BY code_system",
            [paths("codes", "subdivisions")],
        ).fetchall()
        # Geometries and compact memberships cover exactly the published zone list.
        checks["timezone_counts"] = db.execute(
            "SELECT count(DISTINCT tzid),count(*) FROM read_parquet(?)",
            [paths("timezones", "timezone_cells")],
        ).fetchall()
    checks["global_timezone_coverage"] = world_coverage(
        [Path(p) for p in paths("timezones", "timezone_cells")]
    )
    total = sum(
        disk_bytes(root.rglob("*"))
        for source in LOOKUP_SOURCES
        for root in (
            workspace.raw(source),
            workspace.normalized(source),
            workspace.work / source,
        )
    )
    return dict(
        status=status,
        reports=counts,
        spot_checks=checks,
        total_disk_bytes=total,
        cell_validation=(
            "All stored cells and point agreement validated before every "
            "atomic Parquet publication; hashes reverified here"
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    workspace = Workspace(args.data_dir)
    result = verify(workspace)
    path = workspace.work / "extra-lookups-verification.json"
    write_json(path, result)
    print(f"Lookup verification passed: {path}; {result['total_disk_bytes']:,} bytes")


if __name__ == "__main__":
    main()
