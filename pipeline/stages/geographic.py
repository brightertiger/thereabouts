"""Geographic stage identities and units; execution stays in focused stage modules."""

from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

from pipeline.config import policies
from pipeline.config.schema import StageSettings
from pipeline.engines.plate_country.policy import DATA
from pipeline.engines.plate_country.policy import policy as plate_policy
from pipeline.runtime.fingerprints import REPOSITORY, identity, native_versions
from pipeline.runtime.jsonio import Object
from pipeline.runtime.paths import located
from thereabouts.format import CELL_FORMAT_VERSION

from .contract import Context, Unit, make_unit
from .engine_discovery import Discovery


class GeographicStage:
    def __init__(
        self,
        settings: StageSettings,
        discovery: Discovery,
        execute: Callable[[Context, Unit], list[Path]],
        finalize: Callable[[Context], None],
    ) -> None:
        self.settings, self.discovery = settings, discovery
        self.name, self.needs = settings.name, tuple(settings.needs)
        self.execute, self.finalize = execute, finalize

    def identity(self, ctx: Context) -> str:
        tree = asdict(ctx.config)
        return identity(
            [REPOSITORY / path for path in self.settings.packages],
            config={
                "stage": asdict(self.settings),
                **{key: tree[key] for key in self.settings.config},
            },
            pins={},
            native=native_versions(self.settings.native, REPOSITORY / "uv.lock"),
            cell_format=CELL_FORMAT_VERSION if self.settings.cell_format else None,
        )

    def units(self, ctx: Context) -> list[Unit]:
        self.discovery.load(ctx)
        settings = ctx.config.engines
        reconciliation = policies.reconcile(
            located(REPOSITORY, settings.reconcile_policy)
        )
        cities = policies.cities(located(REPOSITORY, settings.city_policies))
        common = {key: value for key, value in cities.items() if key != "countries"}
        resolved: dict[tuple[str, ...], Object] = {}
        current_identity = self.identity(ctx)
        result = []
        for recipe in self.discovery.recipes.get(self.name, []):
            action, _, key = recipe.unit_id.partition("/")
            countries = (
                self.discovery.geography.blocks.get(key, [])
                if action == "block"
                else [key]
                if key in self.discovery.geography.countries
                else self.discovery.geography.countries
            )
            if self.name in {"reconcile", "cells"}:
                policy = cast(Object, reconciliation)
            else:
                group = tuple(countries)
                if group not in resolved:
                    resolved[group] = cast(
                        Object,
                        {
                            **common,
                            "countries": {
                                cc: cities["countries"][cc]
                                for cc in countries
                                if cc in cities["countries"]
                            },
                        },
                    )
                policy = resolved[group]
            if self.name == "evaluate" or (
                self.name == "lookups" and action == "manifest"
            ):
                policy = cast(Object, cities)
            parameters: Object = {"policy": policy}
            if self.name == "plate_country":
                parameters = {
                    "policy": {
                        path.stem: plate_policy(path.stem)
                        for path in sorted(DATA.glob("*.yaml"))
                    }
                }
            if action == "block":
                parameters["countries"] = list(countries)
            if self.name == "evaluate":
                parameters["review"] = policies.read(
                    located(REPOSITORY, settings.city_review)
                )
            unit = make_unit(
                ctx, replace(recipe, parameters=parameters), current_identity
            )
            required = (
                settings.limits.block_reservation_bytes
                if action == "block"
                else settings.limits.lookup_reservation_bytes
                if self.name == "lookups"
                else settings.limits.country_reservation_bytes
            )
            result.append(
                replace(
                    unit,
                    required_bytes=required,
                    refresh_discovery=self.name == "cells" and action == "plan",
                )
            )
        return result

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        if ctx.readonly:
            raise ValueError(
                "Cannot execute a geographic stage with a read-only context"
            )
        return self.execute(ctx, unit)

    def finish(self, ctx: Context) -> None:
        self.finalize(ctx)
