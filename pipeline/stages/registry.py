"""Validate the declared graph before the runner opens a writable workspace."""

from collections.abc import Sequence
from dataclasses import fields

from pipeline.config import Config, policies, reviews
from pipeline.pins.lock import read_lock
from pipeline.runtime.fingerprints import REPOSITORY, native_versions
from pipeline.runtime.paths import located, validate_relative

from . import (
    cells,
    cities,
    evaluate,
    lookups,
    normalize_cells,
    plate_country,
    reconcile,
)
from .contract import Stage
from .dataset import DatasetStage
from .engine_discovery import Discovery
from .geographic import GeographicStage
from .packs import PacksStage
from .publish import PublishStage
from .sources import SourceStage


def ordered(stages: Sequence[Stage]) -> list[Stage]:
    by_name = {stage.name: stage for stage in stages}
    if len(by_name) != len(stages) or "" in by_name:
        raise ValueError("Stage names must be nonempty and unique")
    result: list[Stage] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name not in by_name:
            raise ValueError(f"Unknown stage dependency: {name}")
        if name in visiting:
            raise ValueError(f"Stage dependency cycle at {name}")
        if name in seen:
            return
        visiting.add(name)
        for upstream in by_name[name].needs:
            visit(upstream)
        visiting.remove(name)
        seen.add(name)
        result.append(by_name[name])

    for stage in stages:
        visit(stage.name)
    return result


def registry(config: Config) -> list[Stage]:
    if not config.stages:
        raise ValueError("Configure at least one stage")
    sections = {field.name for field in fields(config)}
    for stage in config.stages:
        if any(name not in sections for name in stage.config):
            raise ValueError(f"Unknown config dependency in {stage.name}")
        for package in stage.packages:
            validate_relative(package)
            if (
                not package.startswith("pipeline/")
                or not (REPOSITORY / package).exists()
            ):
                raise ValueError(f"Missing production code package: {package}")
        native_versions(stage.native, REPOSITORY / "uv.lock")
        if not stage.packages:
            raise ValueError(f"Stage {stage.name} needs an identity package")
    pins = read_lock(REPOSITORY / "pins.lock")
    for name, source in config.sources.items():
        if source.enabled and (name not in pins or not pins[name].available):
            raise ValueError(f"Enabled source has no reviewed pin: {name}")
    policies.reconcile(located(REPOSITORY, config.engines.reconcile_policy))
    policy = policies.cities(located(REPOSITORY, config.engines.city_policies))
    reviews.load(located(REPOSITORY, config.engines.city_review), policy)
    discovery = Discovery({name for name, pin in pins.items() if pin.available})
    implementations = {
        "reconcile": (reconcile.run, reconcile.finish, reconcile.parameters),
        "cells": (cells.run, cells.finish, cells.parameters),
        "cities": (cities.run, cities.finish, cities.parameters),
        "evaluate": (evaluate.run, evaluate.finish, evaluate.parameters),
        "normalize_cells": (
            normalize_cells.run,
            normalize_cells.finish,
            normalize_cells.parameters,
        ),
        "lookups": (lookups.run, lookups.finish, lookups.parameters),
        "plate_country": (
            plate_country.run,
            plate_country.finish,
            plate_country.parameters,
        ),
    }
    releases = {"dataset": DatasetStage, "packs": PacksStage, "publish": PublishStage}
    unknown = {stage.name for stage in config.stages} - {
        "download",
        "normalize",
        *implementations,
        *releases,
    }
    if unknown:
        raise ValueError(f"Unknown stage implementations: {sorted(unknown)}")
    return ordered(
        [
            SourceStage(settings, pins)
            if settings.name in {"download", "normalize"}
            else releases[settings.name](settings)
            if settings.name in releases
            else GeographicStage(settings, discovery, *implementations[settings.name])
            for settings in config.stages
        ]
    )
