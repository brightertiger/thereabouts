"""Reject invalid engine selections and budgets before execution opens files."""

import math
import re
from dataclasses import fields

from h3.api import basic_int as h3

from pipeline.runtime.paths import validate_relative

from .engines import EngineSettings


def validate(settings: EngineSettings, block_resolution: int) -> None:
    if not math.isfinite(settings.minimum_country_coverage) or not (
        0 <= settings.minimum_country_coverage <= 1
    ):
        raise ValueError("engines.minimum_country_coverage must be between 0 and 1")
    for item in fields(settings.limits):
        if getattr(settings.limits, item.name) <= 0:
            raise ValueError(f"engines.limits.{item.name} must be positive")
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
