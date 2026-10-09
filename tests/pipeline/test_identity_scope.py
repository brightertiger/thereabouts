"""Closure dumps: each stage hashes the configuration code it actually reads."""

import ast

from pipeline.config import Config, load
from pipeline.runtime.fingerprints import (
    REPOSITORY,
    adapter_hashes,
    closures,
    stage_identity,
)
from thereabouts.format import CELL_FORMAT_VERSION

STAGES = {
    "download",
    "normalize",
    "reconcile",
    "cells",
    "cities",
    "evaluate",
    "normalize_cells",
    "lookups",
    "plate_country",
    "dataset",
    "packs",
    "publish",
}
GEOGRAPHIC = {
    "reconcile",
    "cells",
    "cities",
    "evaluate",
    "normalize_cells",
    "lookups",
    "plate_country",
}
RELEASE = {"dataset", "packs", "publish"}
LOADER = ("__init__.py", "loader.py", "engine_validation.py", "schema.py")


def holding(dump: dict[str, dict[str, str]], name: str) -> set[str]:
    return {
        stage for stage, files in dump.items() if f"pipeline/config/{name}" in files
    }


def identities(config: Config) -> dict[str, str]:
    return {
        stage.name: stage_identity(stage, config, cell_format=CELL_FORMAT_VERSION)
        for stage in config.stages
    }


def test_closure_dump_scopes_configuration_modules() -> None:
    dump = closures(load())
    assert set(dump) == STAGES
    assert holding(dump, "release.py") == RELEASE
    assert holding(dump, "engines.py") and holding(dump, "engines.py") <= GEOGRAPHIC
    for name in LOADER:
        assert holding(dump, name) == set(), name


def test_adapter_closures_hold_no_release_engine_or_loader_module() -> None:
    config = load()
    forbidden = {f"pipeline/config/{name}" for name in ("release.py", "engines.py")}
    forbidden |= {f"pipeline/config/{name}" for name in LOADER}
    for name, source in config.sources.items():
        files = adapter_hashes(source.adapter)
        assert files and not forbidden & set(files), name


def test_engine_runtime_knobs_change_no_identity() -> None:
    base = identities(load())
    tuned = load(
        overrides=[
            "engines.runtime.sqlite_cache_kib=65536",
            "engines.runtime.duckdb_spill_bytes=1",
            "engines.runtime.country_reservation_bytes=1",
        ]
    )
    assert identities(tuned) == base
    batched = identities(load(overrides=["engines.batches.parquet_batch_rows=2048"]))
    assert {name for name in base if base[name] != batched[name]} == GEOGRAPHIC


def test_merged_engine_limits_expose_both_sections() -> None:
    settings = load(overrides=["engines.runtime.sqlite_cache_kib=7"]).engines
    assert settings.limits.sqlite_cache_kib == 7
    assert settings.limits.parquet_batch_rows == settings.batches.parquet_batch_rows


def test_runtime_does_not_import_the_client_package() -> None:
    for path in sorted((REPOSITORY / "pipeline/runtime").glob("*.py")):
        tree = ast.parse(path.read_bytes())
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not [name for name in names if name.partition(".")[0] == "thereabouts"]
