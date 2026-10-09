"""Declare country, block and table dependencies from source and block inventories."""

from collections.abc import Collection
from pathlib import Path

from pipeline.runtime.records import Dependency, Recipe

from .contract import Context
from .engine_data import Geography, source_manifest
from .sources import PARTITIONS

# The outputs consumers read of each producing stage, as that stage declares them;
# only those are hashed and restored.
READS = {"normalize": PARTITIONS}


def dependencies(
    keys: set[tuple[str, str]], *, evaluation_gate: bool = False
) -> tuple[Dependency, ...]:
    return tuple(
        Dependency(
            *key,
            paths=READS.get(key[0], ()),
            control=evaluation_gate and key[0] == "evaluate",
        )
        for key in sorted(keys)
    )


def registration_enabled(ctx: Context) -> bool:
    source = ctx.config.sources.get(ctx.config.engines.registration_source)
    return source is not None and source.enabled


def plate_recipes(ctx: Context, available: Collection[str]) -> list[Recipe]:
    """`plate_country/world` exists with its registration evidence.

    It reads that source's partitions, and the whole plate-country evidence unit
    (a JSON inventory, not partitions) when that source is enabled and pinned.
    """
    if not registration_enabled(ctx):
        return []
    settings = ctx.config.engines
    parents = list(dependencies({("normalize", settings.registration_source)}))
    evidence = ctx.config.sources.get(settings.plate_country_source)
    if (
        evidence is not None
        and evidence.enabled
        and settings.plate_country_source in available
    ):
        parents.append(Dependency("normalize", settings.plate_country_source))
    return [
        Recipe(
            "plate_country",
            "world",
            dependencies=tuple(sorted(parents, key=lambda item: item.key)),
        )
    ]


def geographic_recipes(ctx: Context, geography: Geography) -> list[Recipe]:
    settings = ctx.config.engines
    codes, blocks = geography.countries, geography.blocks
    if not codes:
        return []
    recipes: list[Recipe] = []

    def add(stage: str, key: str, parents: set[tuple[str, str]]) -> None:
        recipes.append(
            Recipe(
                stage,
                key,
                dependencies=dependencies(
                    parents, evaluation_gate=stage == "normalize_cells"
                ),
            )
        )

    reconciled = {("reconcile", "country/" + cc) for cc in codes}
    qualities = {("reconcile", "quality/" + cc) for cc in codes}
    land = ("reconcile", "land/world")
    normalize = {
        ("normalize", name)
        for name in ctx.config.engines.reconcile_sources
        if name != settings.land_source
    }
    add("reconcile", "land/world", {("normalize", settings.land_source)})
    for cc in codes:
        add("reconcile", "extract/" + cc, normalize)
        add("reconcile", "links/" + cc, {("reconcile", "extract/" + cc)})
        add(
            "reconcile",
            "country/" + cc,
            {("reconcile", f"{action}/{cc}") for action in ("extract", "links")},
        )
        add("reconcile", "quality/" + cc, reconciled | {land})
    add("reconcile", "gate/pilot", reconciled | qualities | {land})
    add(
        "reconcile",
        "manifest/current",
        reconciled | qualities | {land, ("reconcile", "gate/pilot")},
    )
    add("cells", "plan/countries", reconciled | {land})
    for block, countries in blocks.items():
        add(
            "cells",
            "block/" + block,
            {("reconcile", "country/" + cc) for cc in countries} | {land},
        )
    for cc in codes:
        add("cells", "places/" + cc, {("reconcile", "country/" + cc), land})
        add(
            "cities",
            "country/" + cc,
            {("reconcile", "country/" + cc), ("normalize", settings.urban_source)},
        )
        add(
            "cities",
            "mapping/" + cc,
            {("cities", "country/" + cc), ("reconcile", "country/" + cc)},
        )
    add(
        "cells",
        "manifest/current",
        {("cells", "block/" + block) for block in blocks}
        | {("cells", "places/" + cc) for cc in codes},
    )
    add("cells", "snapshot/current", {("cells", "manifest/current")})
    add(
        "cities",
        "manifest/current",
        {
            ("cities", f"{action}/{cc}")
            for cc in codes
            for action in ("country", "mapping")
        },
    )
    add(
        "evaluate",
        "pilot",
        {("cities", "manifest/current"), ("cells", "snapshot/current")},
    )
    gate = ("evaluate", "pilot")
    for block, countries in blocks.items():
        add(
            "normalize_cells",
            "block/" + block,
            {
                ("cells", "block/" + block),
                land,
                ("normalize", settings.urban_source),
                gate,
            }
            | {
                (stage, "country/" + cc)
                for cc in countries
                for stage in ("cities", "reconcile")
            },
        )
    for cc in codes:
        add(
            "normalize_cells",
            "places/" + cc,
            {
                ("cells", "places/" + cc),
                ("cities", "mapping/" + cc),
                ("cities", "country/" + cc),
                gate,
            },
        )
        add(
            "normalize_cells",
            "quality/" + cc,
            {
                (stage, "block/" + block)
                for block, countries in blocks.items()
                if cc in countries
                for stage in ("cells", "normalize_cells")
            }
            | {("cities", "country/" + cc), ("reconcile", "country/" + cc), gate},
        )
    return recipes


def lookup_recipes(ctx: Context, geography: Geography) -> list[Recipe]:
    if not geography.countries:
        return []
    settings = ctx.config.engines
    recipes = []
    countries = {("reconcile", "country/" + cc) for cc in geography.countries}
    for kind, source in settings.static_sources.items():
        manifest = source_manifest(ctx, source)
        if manifest is None:
            continue
        for part in manifest["partitions"]:
            if part["kind"] != kind:
                continue
            parents = {("normalize", source)}
            if ctx.config.sources[source].kind != "timezones":
                parents |= countries
            recipes.append(
                Recipe(
                    "lookups",
                    f"static/{kind}/{Path(part['path']).stem}",
                    dependencies=dependencies(parents),
                )
            )
    for kind, source in settings.spatial_sources.items():
        if source_manifest(ctx, source) is not None:
            parents = {("normalize", source)} | {
                ("normalize_cells", "block/" + b) for b in geography.blocks
            }
            recipes.append(
                Recipe("lookups", "spatial/" + kind, dependencies=dependencies(parents))
            )
    if settings.name_sources:
        parents = {("normalize", source) for source in settings.name_sources} | {
            ("normalize_cells", "places/" + cc) for cc in geography.countries
        }
        recipes.append(
            Recipe("lookups", "names/world", dependencies=dependencies(parents))
        )
    parents = (
        {recipe.key for recipe in recipes}
        | {("normalize_cells", "block/" + b) for b in geography.blocks}
        | {
            ("normalize_cells", f"{action}/{cc}")
            for action in ("places", "quality")
            for cc in geography.countries
        }
    )
    if registration_enabled(ctx):
        parents.add(("plate_country", "world"))
    recipes.append(
        Recipe("lookups", "manifest/current", dependencies=dependencies(parents))
    )
    return recipes
