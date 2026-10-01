"""Checkpoint each timezone, preserving geometry and compacted H3 coverage."""

import json
import time
import zipfile
from collections import Counter
from pathlib import Path

import h3
import h3.api.basic_int as h3i
import shapefile
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from .artifacts import publish_report, read_json
from .geometry import repair_geometry, split_geometry
from .io import fingerprint, write_json
from .ledger import Ledger
from .lifecycle import finish_source, resume_source
from .lookup_h3_cover import COVER_VERSION, cover
from .lookup_iana import zone_rows
from .lookup_normalize import configuration as text_configuration
from .lookup_rows import Row, decorate
from .runtime import resources, single_run, source_budget
from .workspace import Workspace
from .writer import PartitionWriter

SOURCE = "timezones"
ARCHIVE = "timezones-with-oceans.shapefile.zip"


def configuration() -> Row:
    return {
        **text_configuration(),
        "cover": COVER_VERSION,
        "shapely": shapely.__version__,
        "semantics": "res8-center; with-oceans; overlaps retained",
        "geometry_bytes": 4_000_000,
    }


def extract(workspace: Workspace, inventory: Row) -> Path:
    root = workspace.work / SOURCE / "shapes"
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(inventory["files"][ARCHIVE]["path"]) as archive:
        members = [
            i
            for i in archive.infolist()
            if Path(i.filename).suffix in (".shp", ".shx", ".dbf", ".prj")
        ]
        source_budget(workspace, SOURCE, sum(i.file_size for i in members))
        for member in members:
            target = root / Path(member.filename).name
            # Recreate expendable shapes from verified archive bytes on an
            # interrupted run; same-size temporary corruption must not survive.
            with archive.open(member) as src, target.open("wb") as dst:
                import shutil

                shutil.copyfileobj(src, dst, 1024 * 1024)
    shps = list(root.glob("*.shp"))
    if len(shps) != 1:
        raise ValueError("Expected one timezone shapefile")
    return shps[0]


def zone_unit(
    workspace: Workspace, inventory: Row, tzid: str, geometry: BaseGeometry, digest: str
) -> tuple[Row, Row]:
    unit = dict(stage="timezones.normalize", unit_id=tzid, inputs_hash=digest)
    ledger = Ledger(workspace.ledger_path)
    report_path = (
        workspace.normalized(SOURCE)
        / "audits"
        / digest
        / f"{tzid.replace('/', '_')}.json"
    )
    if ledger.is_complete(**unit):
        return unit, read_json(report_path)
    started = time.monotonic()
    geometry, repairs = repair_geometry(
        geometry, collection="collect", force_2d=True, clip_roundoff=True
    )
    cells = cover(geometry)
    pin = inventory["files"][ARCHIVE]
    raw = dict(tzid=tzid, repairs=repairs, coverage=configuration()["semantics"])
    areas = PartitionWriter(workspace, SOURCE, "timezones", tzid, digest)
    for ordinal, part in enumerate(split_geometry(geometry, 4_000_000)):
        row = dict(
            tzid=tzid,
            part=ordinal,
            geometry=part.wkb,
            is_ocean=tzid.startswith("Etc/GMT"),
        )
        areas.add(
            decorate(
                row, SOURCE, f"{tzid}:{ordinal}", pin, inventory["source_release"], raw
            )
        )
    writer = PartitionWriter(workspace, SOURCE, "timezone_cells", tzid, digest)
    resolutions: Counter[str] = Counter()
    expanded = 0
    for cell in cells:
        level = h3i.get_resolution(cell)
        resolutions[str(level)] += 1
        expanded += h3i.cell_to_children_size(cell, 8)
        row = dict(
            tzid=tzid, h3=h3.int_to_str(cell), h3_uint64=cell, h3_resolution=level
        )
        writer.add(
            decorate(
                row, SOURCE, f"{tzid}:{cell:x}", pin, inventory["source_release"], raw
            )
        )
    outputs = [*areas.finish(), *writer.finish()]
    report = dict(
        tzid=tzid,
        cells=len(cells),
        expanded_res8=expanded,
        geometry_parts=areas.count,
        repairs=repairs,
        rejects=0,
        resolutions=dict(resolutions),
        seconds=time.monotonic() - started,
    )
    write_json(report_path, report)
    ledger.complete(**unit, outputs=[*outputs, report_path], metadata=report)
    print(
        f"TIMEZONE {tzid}: {len(cells):,} cells, {report['seconds']:.1f}s", flush=True
    )
    return unit, report


def normalize(workspace: Workspace) -> None:
    with single_run(workspace, SOURCE):
        if resume_source(workspace, SOURCE, configuration()):
            return
        started = time.monotonic()
        inventory = read_json(workspace.raw(SOURCE) / "inventory.json")
        ledger = Ledger(workspace.ledger_path)
        for name, pin in inventory["files"].items():
            if not ledger.is_complete("timezones.download", name, fingerprint(pin)):
                raise ValueError(f"Unverified timezone input {name}")
        digest = fingerprint(dict(inventory=inventory, configuration=configuration()))
        shp = extract(workspace, inventory)
        commits: list[Row] = []
        reports: list[Row] = []
        with shapefile.Reader(str(shp), encoding="utf-8") as reader:
            for record in reader.iterShapeRecords():
                tzid = str(record.record.as_dict()["tzid"])
                unit, report = zone_unit(
                    workspace,
                    inventory,
                    tzid,
                    shape(record.shape.__geo_interface__),
                    digest,
                )
                commits.append(unit)
                reports.append(report)
        names = json.loads(
            Path(
                inventory["files"]["timezone-names-with-oceans.json"]["path"]
            ).read_text()
        )
        expected = set(names if isinstance(names, list) else names["timezones"])
        actual = {report["tzid"] for report in reports}
        if expected != actual:
            raise ValueError(
                f"Timezone names disagree with published list: {expected ^ actual}"
            )
        iana_unit = dict(
            stage="timezones.normalize", unit_id="iana-zone-tables", inputs_hash=digest
        )
        if not ledger.is_complete(**iana_unit):
            writer = PartitionWriter(
                workspace, SOURCE, "zone_tables", "iana-zone-tables", digest
            )
            pin = inventory["files"]["tzdata2026e.tar.gz"]
            for index, row in enumerate(zone_rows(Path(pin["path"]))):
                writer.add(
                    decorate(
                        dict(row),
                        SOURCE,
                        f"iana:{index}",
                        pin,
                        inventory["source_release"],
                        row,
                    )
                )
            ledger.complete(
                **iana_unit, outputs=writer.finish(), metadata={"rows": writer.count}
            )
        commits.append(iana_unit)
        report = dict(
            zones=len(reports),
            publisher_zones=len(expected),
            rejects=0,
            cells=sum(r["cells"] for r in reports),
            geometry_parts=sum(r["geometry_parts"] for r in reports),
            expanded_res8=sum(r["expanded_res8"] for r in reports),
            zones_with_repairs=[r["tzid"] for r in reports if r["repairs"]],
            zones_without_res8_centers=[r["tzid"] for r in reports if not r["cells"]],
            **resources(started),
        )
        summary = publish_report(workspace, SOURCE, report)
        licenses = (
            workspace.normalized(SOURCE) / f"licenses-{fingerprint(inventory)}.json"
        )
        write_json(
            licenses,
            {
                name: {
                    key: pin[key]
                    for key in ("url", "license", "license_url", "attribution")
                }
                for name, pin in inventory["files"].items()
            },
        )
        finish_source(
            workspace,
            SOURCE,
            inventory["source_release"],
            commits,
            [summary, licenses],
            configuration(),
        )
        print(json.dumps(report), flush=True)
