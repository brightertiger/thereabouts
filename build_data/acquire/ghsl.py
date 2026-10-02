"""Pinned GHSL urban centres: resumable acquisition and bounded WGS84 areas."""

from __future__ import annotations

import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import numpy as np
import shapely
from numpy.typing import NDArray

from build_data.reconcile.common import Row, encode

from .artifacts import read_json
from .download import download_file
from .geometry import bounds_columns, repair_geometry
from .io import fingerprint, sha256_file, write_json
from .ledger import Ledger
from .lifecycle import finish_source, resume_source
from .lookup_http import probe
from .runtime import single_run
from .workspace import Workspace
from .writer import PartitionWriter

RELEASE = "R2024A-V1.2"
NAME = "GHS_UCDB_THEME_GENERAL_CHARACTERISTICS_GLOBE_R2024A_V1_2.zip"
URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/"
    "GHS_UCDB_GLOBE_R2024A/GHS_UCDB_THEME_GLOBE_R2024A/"
    "GHS_UCDB_THEME_GENERAL_CHARACTERISTICS_GLOBE_R2024A/V1-2/" + NAME
)
SHA256 = "bc879d82320504f89df2041b7936221c8239cd808abe93980493aed062b4f3d6"
SIZE = 6902089
LICENSE_URL = "https://human-settlement.emergency.copernicus.eu/GHSLhowToCite.php"
ATTRIBUTION = (
    "European Commission, Joint Research Centre (JRC), GHS-UCDB R2024A; "
    "Pesaresi et al. (2024), Advances on the Global Human Settlement Layer by "
    "joint assessment of Earth Observation and population survey data, "
    "International Journal of Digital Earth 17(1). "
    "https://doi.org/10.1080/17538947.2024.2390454"
)


def download(workspace: Workspace) -> None:
    with single_run(workspace, "ghsl"):
        inventory_path = workspace.raw("ghsl") / "inventory.json"
        if inventory_path.exists():
            inventory = read_json(inventory_path)
        else:
            pin = {**probe(URL), "url": URL, "sha256": SHA256, "size": SIZE}
            pin["path"] = str((workspace.raw("ghsl") / NAME).resolve())
            inventory = {
                "source": "ghsl",
                "source_release": RELEASE,
                "files": {NAME: pin},
            }
            write_json(inventory_path, inventory)
        pin = inventory["files"][NAME]
        ledger = Ledger(workspace.ledger_path)
        digest = fingerprint(pin)
        if ledger.is_complete("ghsl.download", NAME, digest):
            return
        path = Path(pin["path"])
        download_file(
            URL,
            path,
            expected_size=SIZE,
            etag=pin["etag"],
            last_modified=pin["last_modified"],
            retries=60,
        )
        if sha256_file(path) != SHA256:
            raise ValueError("GHSL package differs from reviewed pin")
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise ValueError("Invalid GHSL ZIP CRC")
        ledger.complete("ghsl.download", NAME, digest, [path])


def inverse_mollweide(xy: NDArray[np.float64]) -> NDArray[np.float64]:
    """Inverse ESRI:54009 (WGS84 semimajor axis), as declared by this package."""
    radius = 6378137.0
    theta = np.arcsin(np.clip(xy[:, 1] / (np.sqrt(2) * radius), -1, 1))
    latitude = np.arcsin(np.clip((2 * theta + np.sin(2 * theta)) / np.pi, -1, 1))
    longitude = np.pi * xy[:, 0] / (2 * np.sqrt(2) * radius * np.cos(theta))
    return cast(NDArray[np.float64], np.rad2deg(np.column_stack((longitude, latitude))))


def records(path: Path) -> Iterator[Row]:
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        table, column, srs = db.execute(
            "SELECT table_name,column_name,srs_id FROM gpkg_geometry_columns"
        ).fetchone()
        definition = db.execute(
            "SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id=?", (srs,)
        ).fetchone()[0]
        if "Mollweide" not in definition or "6378137" not in definition:
            raise ValueError("Unexpected GHSL CRS")
        # Identifiers come from the pinned, checksum-verified GeoPackage schema.
        query = 'SELECT * FROM "' + table.replace('"', '""') + '"'
        cursor = db.execute(query)
        names = [c[0] for c in cursor.description]
        for values in cursor:
            row = dict(zip(names, values, strict=True))
            blob = row.pop(column)
            envelope = (blob[3] >> 1) & 7
            lengths = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
            if blob[:2] != b"GP" or envelope not in lengths:
                raise ValueError("Invalid GeoPackage geometry header")
            geometry = shapely.from_wkb(blob[8 + lengths[envelope] :])
            geometry = shapely.transform(geometry, inverse_mollweide)
            geometry, changes = repair_geometry(geometry, collection="collect")
            identity = str(row["ID_UC_G0"])
            yield {
                "source": "ghsl",
                "source_id": identity,
                "entity_id": identity,
                "kind": "urban_centre",
                "subtype": "built_up",
                "geometry": geometry.wkb,
                "name": row.get("GC_UCN_MN_2025") or None,
                **bounds_columns(geometry),
                "source_release": RELEASE,
                "license": "CC-BY-4.0",
                "provenance": encode(
                    {
                        "source_url": URL,
                        "license_url": LICENSE_URL,
                        "attribution": ATTRIBUTION,
                        "upstream": row,
                        "geometry_changes": ["inverse Mollweide", *changes],
                    }
                ),
            }
    finally:
        db.close()


def normalize(workspace: Workspace) -> None:
    config = {"builder": sha256_file(Path(__file__)), "release": RELEASE}
    with single_run(workspace, "ghsl"):
        if resume_source(workspace, "ghsl", config):
            return
        inventory = read_json(workspace.raw("ghsl") / "inventory.json")
        pin = inventory["files"][NAME]
        ledger = Ledger(workspace.ledger_path)
        if not ledger.is_complete("ghsl.download", NAME, fingerprint(pin)):
            raise ValueError("GHSL download not verified")
        digest = fingerprint({"input": pin, "config": config})
        unit = {"stage": "ghsl.normalize", "unit_id": "world", "inputs_hash": digest}
        if not ledger.is_complete(**unit):
            directory = workspace.work / "ghsl"
            directory.mkdir(parents=True, exist_ok=True)
            extracted = directory / "centres.gpkg"
            with zipfile.ZipFile(pin["path"]) as archive:
                members = [n for n in archive.namelist() if n.endswith(".gpkg")]
                if len(members) != 1:
                    raise ValueError("Expected one GHSL GeoPackage")
                extracted.write_bytes(archive.read(members[0]))
            writer = PartitionWriter(workspace, "ghsl", "areas", "world", digest)
            for row in records(extracted):
                writer.add(row)
            if writer.count != 11422:
                raise ValueError("GHSL count differs from pinned 11,422 centres")
            outputs = writer.finish()
            ledger.complete(**unit, outputs=outputs, metadata={"rows": writer.count})
            extracted.unlink()
        licenses = workspace.normalized("ghsl") / "licenses.json"
        write_json(
            licenses,
            {
                "license": "CC-BY-4.0",
                "url": LICENSE_URL,
                "attribution": ATTRIBUTION,
                "source_url": URL,
            },
        )
        finish_source(workspace, "ghsl", RELEASE, [unit], [licenses], config)
