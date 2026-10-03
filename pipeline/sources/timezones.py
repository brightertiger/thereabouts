"""Pinned timezone polygons, compacted H3 coverage and IANA zone tables."""

import json
from collections import Counter
from pathlib import Path

import h3
import h3.api.basic_int as h3i
import shapefile
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from pipeline.config.source_options import Timezones as Options
from pipeline.config.sources import SourceSettings
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.jsonio import write_json

from .contract import SourceContext
from .proposals.resolve import propose as propose_pin
from .shared.archives import extract
from .shared.geometry import repair_geometry, split_geometry
from .shared.h3_cover import cover
from .shared.iana import zone_rows
from .shared.lookup_rows import Row, decorate
from .shared.manifest import finish
from .shared.writer import PartitionWriter


def evidence(ctx: SourceContext, pin: PinFile) -> Row:
    return {
        "url": pin.url,
        "license": ctx.settings.licence.id,
        "license_url": ctx.settings.licence.url,
        "attribution": ctx.settings.licence.attribution,
        "retrieved_at": ctx.pin.pinned_at,
        **pin.metadata,
    }


def zone(
    ctx: SourceContext, pin: PinFile, tzid: str, geometry: BaseGeometry
) -> tuple[list[Path], Row]:
    geometry, repairs = repair_geometry(
        geometry, collection="collect", force_2d=True, clip_roundoff=True
    )
    options = ctx.settings.options
    resolution = ctx.runtime.config.h3.cell_resolution
    cells = cover(geometry, resolution, int(options["cover_batch_rows"]))
    raw = dict(tzid=tzid, repairs=repairs, coverage=options["semantics"])
    provenance = evidence(ctx, pin)
    areas = PartitionWriter(ctx, "timezones", tzid)
    for ordinal, part in enumerate(
        split_geometry(
            geometry,
            int(options["geometry_bytes"]),
            max_depth=int(options["geometry_max_depth"]),
        )
    ):
        row = dict(
            tzid=tzid,
            part=ordinal,
            geometry=part.wkb,
            is_ocean=tzid.startswith("Etc/GMT"),
        )
        areas.add(
            decorate(
                row,
                ctx.settings.name,
                f"{tzid}:{ordinal}",
                provenance,
                ctx.pin.release,
                raw,
            )
        )
    writer = PartitionWriter(ctx, "timezone_cells", tzid)
    levels: Counter[str] = Counter()
    expanded = 0
    for cell in cells:
        level = h3i.get_resolution(cell)
        levels[str(level)] += 1
        expanded += h3i.cell_to_children_size(cell, resolution)
        row = dict(
            tzid=tzid, h3=h3.int_to_str(cell), h3_uint64=cell, h3_resolution=level
        )
        writer.add(
            decorate(
                row,
                ctx.settings.name,
                f"{tzid}:{cell:x}",
                provenance,
                ctx.pin.release,
                raw,
            )
        )
    return [*areas.finish(), *writer.finish()], dict(
        tzid=tzid,
        cells=len(cells),
        expanded_cells=expanded,
        geometry_parts=areas.count,
        repairs=repairs,
        resolutions=dict(levels),
    )


def normalize(ctx: SourceContext) -> list[Path]:
    options = ctx.settings.options
    pin = ctx.named(str(options["boundary_file"]))
    directory = ctx.work / ctx.unit.inputs_hash
    shapes = extract(
        ctx,
        ctx.input(pin.name),
        directory / "shapes",
        lambda name: Path(name).suffix in (".shp", ".shx", ".dbf", ".prj"),
    )
    shps = [path for path in shapes if path.suffix == ".shp"]
    if len(shps) != 1:
        raise ValueError("Expected one timezone shapefile")
    reports: list[Row] = []
    outputs: list[Path] = []
    with shapefile.Reader(str(shps[0]), encoding="utf-8") as reader:
        for record in reader.iterShapeRecords():
            ctx.runtime.guard.admit()
            paths, report = zone(
                ctx,
                pin,
                str(record.record.as_dict()["tzid"]),
                shape(record.shape.__geo_interface__),
            )
            outputs.extend(paths)
            reports.append(report)
    names = json.loads(
        ctx.input(ctx.named(str(options["names_file"])).name).read_bytes()
    )
    expected = set(names if isinstance(names, list) else names["timezones"])
    actual = {report["tzid"] for report in reports}
    if actual != expected or len(actual) != len(reports):
        raise ValueError(f"Timezone names disagree with publisher: {actual ^ expected}")
    writer = PartitionWriter(ctx, "zone_tables", "iana-zone-tables")
    iana = [
        pin for pin in ctx.pin.files if pin.name.endswith(str(options["iana_suffix"]))
    ]
    if len(iana) != 1:
        raise ValueError("Expected one pinned IANA archive")
    pin = iana[0]
    for index, row in enumerate(
        zone_rows(ctx.input(pin.name), grid=ctx.runtime.config.h3)
    ):
        writer.add(
            decorate(
                dict(row),
                ctx.settings.name,
                f"iana:{index}",
                evidence(ctx, pin),
                ctx.pin.release,
                row,
            )
        )
    outputs.extend(writer.finish())
    report_path = directory / "report.json"
    write_json(
        ctx.ensure(report_path), {"zones": reports, "publisher_zones": len(expected)}
    )
    return finish(ctx, outputs, [*shapes, report_path])


__all__ = ["Options", "normalize", "propose"]


def propose(settings: SourceSettings) -> SourcePin:
    """Resolve upstream only for an explicit pin proposal."""
    return propose_pin(settings)
