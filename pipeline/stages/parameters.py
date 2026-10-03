"""Compose unit policies and resource reservations without knowing stage names."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pipeline.config import policies
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import Object
from pipeline.runtime.paths import located
from pipeline.runtime.records import Recipe

from .contract import Context
from .engine_data import Geography

Policy = Callable[[Recipe], Object]


@dataclass(frozen=True)
class Options:
    parameters: Object
    required_bytes: int
    refresh_discovery: bool = False


Configure = Callable[[Recipe], Options]


def constant(value: Object) -> Policy:
    def select(recipe: Recipe) -> Object:
        return value

    return select


def selected_countries(recipe: Recipe, geography: Geography) -> list[str]:
    action, _, key = recipe.unit_id.partition("/")
    if action == "block":
        return geography.blocks.get(key, [])
    return [key] if key in geography.countries else geography.countries


def reconciliation(ctx: Context) -> Object:
    return cast(
        Object,
        policies.reconcile(located(REPOSITORY, ctx.config.engines.reconcile_policy)),
    )


def cities(ctx: Context) -> Object:
    return cast(
        Object, policies.cities(located(REPOSITORY, ctx.config.engines.city_policies))
    )


def country_policy(value: Object, geography: Geography) -> Policy:
    common = {key: item for key, item in value.items() if key != "countries"}
    overrides = cast(Object, value["countries"])
    resolved: dict[tuple[str, ...], Object] = {}

    def select(recipe: Recipe) -> Object:
        countries = tuple(selected_countries(recipe, geography))
        if countries not in resolved:
            resolved[countries] = {
                **common,
                "countries": {cc: overrides[cc] for cc in countries if cc in overrides},
            }
        return resolved[countries]

    return select


def prepare(
    policy: Policy,
    geography: Geography,
    *,
    country_bytes: int,
    block_bytes: int,
    extra: Object | None = None,
    refresh_plan: bool = False,
) -> Configure:
    def configure(recipe: Recipe) -> Options:
        action = recipe.unit_id.partition("/")[0]
        parameters = {"policy": policy(recipe), **(extra or {})}
        if action == "block":
            parameters["countries"] = list(selected_countries(recipe, geography))
        return Options(
            parameters,
            block_bytes if action == "block" else country_bytes,
            refresh_plan and action == "plan",
        )

    return configure
