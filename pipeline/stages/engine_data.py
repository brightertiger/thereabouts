"""Read source and retained geographic inventories without enumerating recipes."""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from pipeline.runtime.paths import located

from .contract import Context

Row = dict[str, Any]


def read(ctx: Context, name: str) -> Row:
    payload = ctx.verifier.overlay.get(name)
    value = json.loads(
        payload if payload is not None else located(ctx.root, name).read_bytes()
    )
    if not isinstance(value, dict):
        raise ValueError(f"Expected an artifact object: {name}")
    return value


def source_manifest(ctx: Context, source: str) -> Row | None:
    name = f"{ctx.config.paths.normalized}/{source}/manifest.json"
    if name not in ctx.verifier.overlay and not located(ctx.root, name).is_file():
        return None
    value = read(ctx, name)
    if value.get("source") != source:
        raise ValueError(f"Source manifest name mismatch: {name}")
    return value


def available_path(ctx: Context, current: str, retained: str) -> Path | None:
    for name in (current, retained):
        path = located(ctx.root, name)
        if path.is_file():
            return path
    return None


def countries(ctx: Context) -> list[str]:
    settings = ctx.config.engines
    if settings.countries:
        return sorted(settings.countries)
    # Only the narrow country column is needed; no geometry is materialized.
    selected: set[str] = set()
    with duckdb.connect() as db:
        db.execute("SET memory_limit=?", [ctx.config.resources.duckdb_memory])
        db.execute("SET threads=?", [ctx.config.resources.duckdb_threads])
        for name in settings.reconcile_sources:
            if name == "osm_land":
                continue
            manifest = source_manifest(ctx, name)
            if manifest is None:
                return []
            kind = "places" if name == "geonames" else "areas"
            paths = [
                str(located(ctx.root, str(row["path"])))
                for row in manifest["partitions"]
                if row["kind"] == kind
            ]
            if paths:
                db.read_parquet(paths).create_view("country_parts", replace=True)
                selected.update(
                    str(cc)
                    for (cc,) in db.execute(
                        "SELECT DISTINCT country_code FROM country_parts "
                        "WHERE country_code IS NOT NULL"
                    ).fetchall()
                )
    return sorted(selected)


@dataclass
class Geography:
    countries: list[str]
    blocks: dict[str, list[str]]


def geography(ctx: Context) -> Geography:
    codes = countries(ctx)
    if not codes:
        return Geography([], {})
    settings = ctx.config.engines
    path = available_path(ctx, settings.block_index, settings.retained_block_index)
    selected = set(settings.blocks)
    blocks = {}
    if path is not None:
        with closing(
            sqlite3.connect(path.absolute().as_uri() + "?mode=ro&immutable=1", uri=True)
        ) as db:
            for key, values in db.execute(
                "SELECT root,countries FROM blocks ORDER BY root"
            ):
                if not selected or key in selected:
                    required = json.loads(values)
                    missing = set(required) - set(codes)
                    if missing:
                        raise ValueError(
                            f"Block {key} requires unselected countries: "
                            f"{sorted(missing)}"
                        )
                    blocks[str(key)] = required
        if selected - blocks.keys():
            raise ValueError(
                f"Selected blocks absent from index: {sorted(selected - blocks.keys())}"
            )
    return Geography(codes, blocks)
