"""Wide evidence reads must be declared even when the output unit is one country."""

import sqlite3
from pathlib import Path

import h3
import pytest

from pipeline.config import load
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency
from pipeline.stages.engine_data import Geography, geography
from pipeline.stages.engine_recipes import geographic_recipes, lookup_recipes

from .helpers import context


def test_quality_and_static_lookups_declare_country_databases(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        ctx.config = load()
        ctx.verifier.overlay["normalized/codes/manifest.json"] = (
            b'{"source":"codes","partitions":[{"kind":"countries","path":"normalized/codes/countries/part.parquet"}]}'
        )
        geo = Geography(["AA", "BB"], {})
        recipes = {
            r.key: r for r in geographic_recipes(ctx, geo) + lookup_recipes(ctx, geo)
        }
        countries = {
            Dependency("reconcile", "country/AA"),
            Dependency("reconcile", "country/BB"),
        }
        assert countries <= set(recipes["reconcile", "quality/AA"].dependencies)
        assert countries <= set(
            recipes["lookups", "static/countries/part"].dependencies
        )
        assert not any(
            d.stage == "cells"
            for d in recipes["lookups", "static/countries/part"].dependencies
        )


def test_selected_block_requires_every_country(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        ctx.config = load()
        ctx.config.engines.countries = ["AA"]
        block = h3.latlng_to_cell(0, 0, 3)
        ctx.config.engines.blocks = [block]
        path = tmp_path / ctx.config.engines.block_index
        path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(path)
        try:
            db.execute("CREATE TABLE blocks(root TEXT, countries TEXT)")
            db.execute("INSERT INTO blocks VALUES(?,?)", (block, '["AA","BB"]'))
            db.commit()
        finally:
            db.close()
        with pytest.raises(ValueError, match=r"unselected countries.*BB"):
            geography(ctx)


def test_source_roles_and_kinds_do_not_depend_on_source_names(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        ctx.config = load()
        settings = ctx.config.engines
        settings.land_source = "coast"
        settings.reconcile_sources["coast"] = settings.reconcile_sources.pop("osm_land")
        settings.urban_source = "urban"
        settings.static_sources = {"timezone_cells": "clock_zones"}
        source = ctx.config.sources.pop("timezones")
        source.name = "clock_zones"
        ctx.config.sources[source.name] = source
        ctx.verifier.overlay["normalized/clock_zones/manifest.json"] = (
            b'{"source":"clock_zones","partitions":[{"kind":"timezone_cells","path":"normalized/clock_zones/cells.parquet"}]}'
        )
        geo = Geography(["BE"], {"block": ["BE"]})
        recipes = {
            r.key: r for r in geographic_recipes(ctx, geo) + lookup_recipes(ctx, geo)
        }
        assert recipes["reconcile", "land/world"].dependencies == (
            Dependency("normalize", "coast"),
        )
        assert (
            Dependency("normalize", "urban")
            in recipes["cities", "country/BE"].dependencies
        )
        assert (
            Dependency("normalize", "urban")
            in recipes["normalize_cells", "block/block"].dependencies
        )
        assert recipes["lookups", "static/timezone_cells/cells"].dependencies == (
            Dependency("normalize", "clock_zones"),
        )


def test_missing_configured_source_role_fails_during_load() -> None:
    with pytest.raises(ValueError, match=r"source references.*missing"):
        load(overrides=["engines.urban_source=missing"])
