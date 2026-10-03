"""Publish source-evidence code links and spatial joins without dropping rows."""

import shutil
from pathlib import Path
from typing import cast

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.engines import query
from pipeline.engines.cells import joins
from pipeline.engines.cells.code_links import CodeIndex, linked_rows
from pipeline.engines.cells.inputs import Inputs
from pipeline.engines.cells.phone import PhoneCountries
from pipeline.engines.cells.schemas import strings
from pipeline.engines.reconcile.common import Row
from pipeline.engines.storage import file_record, parquet
from pipeline.runtime.jsonio import Object, atomic_output, write_json
from pipeline.runtime.paths import located
from pipeline.runtime.records import Recipe

from . import engine_io as io
from . import lookup_manifest, reconcile
from . import parameters as unit_parameters
from .contract import Context, Unit
from .engine_data import Geography, countries, source_manifest


def static(ctx: Context, unit: Unit, root: Path, key: str) -> list[Path]:
    kind, _, name = key.partition("/")
    source = ctx.config.engines.static_sources[kind]
    manifest = source_manifest(ctx, source)
    if manifest is None:
        raise ValueError(f"Missing lookup source: {source}")
    parts = [
        r
        for r in manifest["partitions"]
        if r["kind"] == kind and Path(r["path"]).stem == name
    ]
    if len(parts) != 1:
        raise ValueError(f"Expected one lookup input: {key}")
    part = parts[0]
    original = located(ctx.root, part["path"])
    path = root / kind / f"{name}.parquet"
    if ctx.config.sources[source].kind == "timezones":
        with atomic_output(path) as temporary:
            shutil.copyfile(original, temporary)
        return [path]
    codes = countries(ctx)
    inputs = Inputs(
        {
            cc: {"path": str(path)}
            for cc, path in reconcile.country_paths(ctx, codes).items()
        },
        {},
        {},
        set(codes),
    )
    index = CodeIndex(inputs)
    phone = None
    if ctx.config.sources[source].kind == "phone":
        phone = PhoneCountries(
            [
                located(ctx.root, p["path"])
                for p in manifest["partitions"]
                if p["kind"] == "phone_metadata"
            ]
        )
    schema = pq.read_schema(original)
    for field in [
        *strings("country_id place_id link_status link_method"),
        pa.field("place_ids", pa.list_(pa.string())),
    ]:
        schema = schema.append(field)
    parquet(
        ctx.root,
        path,
        linked_rows(
            original,
            kind,
            inputs,
            index.countries,
            index.codes,
            index=index,
            phone=phone,
        ),
        schema,
        ctx.config.engines.limits.parquet_batch_rows,
    )
    if pq.read_metadata(path).num_rows != part["rows"]:
        raise ValueError("Code linking changed source cardinality")
    return [path]


def spatial(ctx: Context, unit: Unit, root: Path, kind: str) -> list[Path]:
    source = ctx.config.engines.spatial_sources[kind]
    manifest = source_manifest(ctx, source)
    if manifest is None:
        raise ValueError(f"Missing spatial lookup source: {source}")
    parts = [part for part in manifest["partitions"] if part["kind"] == kind]
    tables = [
        io.local(
            ctx,
            io.table(
                ctx,
                "normalize_cells",
                dep.unit_id,
                "cells",
                block=dep.unit_id.removeprefix("block/"),
            ),
        )
        for dep in unit.recipe.dependencies
        if dep.stage == "normalize_cells"
    ]
    limits = ctx.config.engines.limits
    db = query.connect(root / "spill", ctx.config.resources, limits)
    destination = root / kind / "joined.parquet"
    try:
        groups = joins.prepare(db, tables)
        db.read_parquet([str(located(ctx.root, p["path"])) for p in parts]).create_view(
            "source"
        )
        joins.assignments(db, groups)
        sql = """SELECT s.*, a.country_id,a.state_id,a.city_id,
          a.cell_country_code, coalesce(a.cell_status,'unlocated') AS cell_status,
          CASE WHEN s.country_code IS NOT NULL AND a.country_id IS NOT NULL
               THEN s.country_code<>a.cell_country_code END AS country_disagrees
          FROM source s LEFT JOIN assignments a USING(h3_uint64)"""
        with atomic_output(destination) as temporary:
            db.sql(sql).write_parquet(
                str(temporary),
                compression="zstd",
                row_group_size=limits.join_row_group_rows,
            )
            if pq.read_metadata(temporary).num_rows != sum(p["rows"] for p in parts):
                raise ValueError("Spatial join changed source cardinality")
        db.read_parquet(str(destination)).create_view("joined")
        counts = dict(
            db.execute("SELECT cell_status,count(*) FROM joined GROUP BY 1").fetchall()
        )
        row = db.execute(
            "SELECT count(*) FILTER (WHERE country_disagrees),"
            "count(country_disagrees) FROM joined"
        ).fetchone()
        if row is None:
            raise ValueError("Spatial join produced no accounting result")
        counts.update(disagreements=row[0], compared=row[1])
    finally:
        db.close()
    receipt = root / kind / "joined.json"
    write_json(
        receipt,
        {
            **file_record(ctx.root, destination),
            "kind": kind,
            "rows": sum(p["rows"] for p in parts),
            "counts": counts,
        },
    )
    return [destination, receipt]


def run(ctx: Context, unit: Unit) -> list[Path]:
    action, _, key = unit.recipe.unit_id.partition("/")
    root = located(ctx.root, ctx.config.paths.cells) / "lookups" / unit.inputs_hash
    if action == "static":
        return static(ctx, unit, root, key)
    if action == "spatial":
        return spatial(ctx, unit, root, key)
    if action == "manifest":
        return lookup_manifest.publish(
            ctx, unit, root, cast(Row, unit.recipe.parameters["policy"])
        )
    raise ValueError(f"Unknown lookup action: {action}")


def finish(ctx: Context) -> None:
    """The manifest unit enforces integrity before recording completion."""


def parameters(ctx: Context, geography: Geography) -> unit_parameters.Configure:
    policy = unit_parameters.cities(ctx)
    country = unit_parameters.country_policy(policy, geography)

    def select(recipe: Recipe) -> Object:
        return policy if recipe.unit_id == "manifest/current" else country(recipe)

    limits = ctx.config.engines.limits
    return unit_parameters.prepare(
        select,
        geography,
        country_bytes=limits.lookup_reservation_bytes,
        block_bytes=limits.block_reservation_bytes,
    )
