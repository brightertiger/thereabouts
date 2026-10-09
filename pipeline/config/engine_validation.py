"""Reject invalid engine selections and budgets before execution opens files."""

import math
import re
from dataclasses import fields

from h3.api import basic_int as h3

from pipeline.runtime.paths import validate_relative

from .engines import EngineSettings
from .sources import SourceSettings


def validate(settings: EngineSettings, block_resolution: int) -> None:
    if not math.isfinite(settings.minimum_country_coverage) or not (
        0 <= settings.minimum_country_coverage <= 1
    ):
        raise ValueError("engines.minimum_country_coverage must be between 0 and 1")
    for section in ("batches", "runtime"):
        values = getattr(settings, section)
        for item in fields(values):
            if getattr(values, item.name) <= 0:
                raise ValueError(f"engines.{section}.{item.name} must be positive")
    for name in (
        "reconcile_policy",
        "city_policies",
        "city_review",
        "evaluation_points",
        "country_inventory",
        "block_index",
        "retained_country_inventory",
        "retained_block_index",
    ):
        validate_relative(getattr(settings, name))
    if len(set(settings.countries)) != len(settings.countries) or any(
        not re.fullmatch(r"[A-Z]{2}", cc) for cc in settings.countries
    ):
        raise ValueError(
            "engines.countries must contain unique uppercase country codes"
        )
    for block in settings.blocks:
        try:
            value = int(block, 16)
        except ValueError as error:
            raise ValueError(f"Invalid selected H3 block: {block}") from error
        if not h3.is_valid_cell(value) or h3.get_resolution(value) != block_resolution:
            raise ValueError(f"Invalid selected H3 block: {block}")
    if len(set(settings.blocks)) != len(settings.blocks):
        raise ValueError("engines.blocks must be unique")


def validate_sources(
    settings: EngineSettings, sources: dict[str, SourceSettings]
) -> None:
    selected = (
        set(settings.reconcile_sources)
        | set(settings.static_sources.values())
        | set(settings.spatial_sources.values())
        | {
            settings.land_source,
            settings.urban_source,
            settings.registration_source,
            settings.plate_country_source,
        }
    ) - {""}
    missing = selected - sources.keys()
    if missing:
        raise ValueError(
            f"Engine source references are not configured: {sorted(missing)}"
        )
    roles = {
        "land_source": "land",
        "urban_source": "urban_centres",
        "registration_source": "registration_evidence",
        "plate_country_source": "registration_country_evidence",
    }
    for name, kind in roles.items():
        source = getattr(settings, name)
        if source and sources[source].kind != kind:
            raise ValueError(f"engines.{name} requires source kind {kind}")
    if settings.reconcile_sources and (
        settings.land_source not in settings.reconcile_sources
        or not settings.urban_source
    ):
        raise ValueError(
            "Engine reconciliation requires configured land and urban sources"
        )
