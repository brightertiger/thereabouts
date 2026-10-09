"""Bounded spatial batches from verified SHX entries; no land feature is dropped."""

from pathlib import Path

import shapefile

from pipeline.runtime.jsonio import digest, sha256_file, write_json
from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.archives import extract
from pipeline.sources.shared.manifest import finish
from pipeline.sources.shared.writer import PartitionWriter

from .reader import _build_index, _feature, _publisher_notice, _units
from .rows import _row


def normalize(ctx: SourceContext) -> list[Path]:
    if len(ctx.pin.files) != 1:
        raise ValueError("Expected one OSM land archive")
    pin = ctx.pin.files[0]
    directory = ctx.work / ctx.inputs_hash
    extracted = extract(
        ctx,
        ctx.input(pin.name),
        directory / "shapes",
        lambda name: (
            Path(name).suffix in (".shp", ".shx", ".dbf", ".prj")
            or Path(name).name == "README.txt"
        ),
    )
    shps = [path for path in extracted if path.suffix == ".shp"]
    if len(shps) != 1:
        raise ValueError("Expected one OSM land shapefile")
    shp = shps[0]
    projection = shp.with_suffix(".prj").read_text()
    if 'GEOGCS["GCS_WGS_1984"' not in projection or 'UNIT["Degree"' not in projection:
        raise ValueError(f"Unexpected OSM land CRS: {projection}")
    index = ctx.ensure(directory / "records.sqlite3")
    reservation = int(ctx.settings.options["index_bytes"])
    ctx.guard.admit(reservation)
    written = 0
    try:
        count = _build_index(ctx, shp, index)
        written = index.stat().st_size
        if written > reservation:
            raise ValueError("OSM index exceeds configured index_bytes")
    finally:
        ctx.guard.release(reservation, written_bytes=written)
    notice = _publisher_notice(ctx, shp, count)
    source_hash = sha256_file(shp)
    evidence = {
        "attribution": ctx.settings.licence.attribution,
        "retrieved_at": ctx.pin.pinned_at,
        **pin.metadata,
    }
    outputs: list[Path] = []
    auxiliary = [*extracted, index]
    retained = 0
    with shapefile.Reader(str(shp)) as reader:
        if reader.numRecords != count:
            raise ValueError("OSM SHX and DBF record counts disagree")
        for key, ordinals, extent in _units(ctx, index):
            ctx.guard.admit()
            writer = PartitionWriter(ctx, "areas", key)
            repairs = []
            for ordinal in ordinals:
                row, repair = _row(
                    ctx, *_feature(reader, ordinal), ordinal, evidence, source_hash
                )
                writer.add(row)
                if repair is not None:
                    repairs.append(repair)
            outputs.extend(writer.finish())
            retained += writer.count
            audit = ctx.normalized / "audits" / ctx.inputs_hash / f"{digest(key)}.json"
            write_json(
                ctx.ensure(audit),
                {
                    "records": ordinals,
                    "extent": extent,
                    "repairs": repairs,
                    "rows": writer.count,
                    "rejected_records": 0,
                },
            )
            auxiliary.append(audit)
    if retained != count:
        raise ValueError("OSM output count differs from every pinned source record")
    report = directory / "report.json"
    write_json(
        ctx.ensure(report),
        {"source_count": count, "rows": retained, "publisher": notice},
    )
    return finish(ctx, outputs, [*auxiliary, report])
