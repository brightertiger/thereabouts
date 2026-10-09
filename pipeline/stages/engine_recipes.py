"""Declare country, block and table dependencies from source and block inventories."""

from collections.abc import Iterable, Mapping
from pathlib import Path

from pipeline.runtime.outputs import role
from pipeline.runtime.records import Dependency, Recipe

from .contract import Context
from .engine_data import Geography, source_manifest

Key = tuple[str, str]


def dependencies(
    keys: set[Key],
    *,
    evaluation_gate: bool = False,
    reads: Mapping[Key, tuple[str, ...]] | None = None,
) -> tuple[Dependency, ...]:
    """Dependencies with `reads` patterns hash and restore only those outputs."""
    return tuple(
        Dependency(
            *key,
            paths=(reads or {}).get(key, ()),
            control=evaluation_gate and key[0] == "evaluate",
        )
        for key in sorted(keys)
    )


def partitions(ctx: Context, source: str, kinds: Iterable[str]) -> tuple[str, ...]:
    """Role patterns of a source's normalized partitions; caches and audits excluded."""
    root = ctx.config.paths.normalized
    return tuple(f"{root}/{source}/{kind}/*.parquet" for kind in sorted(kinds))


def geographic_recipes(ctx: Context, geography: Geography) -> list[Recipe]:
    settings = ctx.config.engines
    codes, blocks = geography.countries, geography.blocks
    if not codes:
        return []
    recipes: list[Recipe] = []

    urban = ("normalize", settings.urban_source)
    reads = {
        ("normalize", name): partitions(ctx, name, kinds)
        for name, kinds in settings.reconcile_sources.items()
    } | {
        ("normalize", settings.land_source): partitions(
            ctx, settings.land_source, ["areas"]
        ),
        urban: partitions(ctx, settings.urban_source, ["areas"]),
    }

    def add(stage: str, key: str, parents: set[Key]) -> None:
        recipes.append(
            Recipe(
                stage,
                key,
                dependencies=dependencies(
                    parents, evaluation_gate=stage == "normalize_cells", reads=reads
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
            read: tuple[str, ...] = (role(part["path"]),)
            if ctx.config.sources[source].kind == "phone":
                read += partitions(ctx, source, ["phone_metadata"])
            recipes.append(
                Recipe(
                    "lookups",
                    f"static/{kind}/{Path(part['path']).stem}",
                    dependencies=dependencies(
                        parents, reads={("normalize", source): read}
                    ),
                )
            )
    for kind, source in settings.spatial_sources.items():
        if source_manifest(ctx, source) is not None:
            parents = {("normalize", source)} | {
                ("normalize_cells", "block/" + b) for b in geography.blocks
            }
            reads = {("normalize", source): partitions(ctx, source, [kind])}
            recipes.append(
                Recipe(
                    "lookups",
                    "spatial/" + kind,
                    dependencies=dependencies(parents, reads=reads),
                )
            )
    names: dict[str, list[str]] = {}
    for source, kinds in settings.name_sources.items():
        manifest = source_manifest(ctx, source)
        published = {p["kind"] for p in manifest["partitions"]} if manifest else set()
        if published & set(kinds):
            names[source] = sorted(published & set(kinds))
    if names:
        reads = {("normalize", s): partitions(ctx, s, k) for s, k in names.items()}
        places = {("normalize_cells", "places/" + cc) for cc in geography.countries}
        recipes.append(
            Recipe(
                "lookups",
                "names/world",
                dependencies=dependencies(set(reads) | places, reads=reads),
            )
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
    if plate_recipe(ctx) is not None:
        parents.add(("plate_country", "world"))
    recipes.append(
        Recipe("lookups", "manifest/current", dependencies=dependencies(parents))
    )
    return recipes


def plate_recipe(ctx: Context) -> Recipe | None:
    """Plate tables need only normalized registration evidence; a pinned
    plate-country source adds documents and vehicle priors."""
    settings = ctx.config.engines
    if source_manifest(ctx, settings.registration_source) is None:
        return None
    reads = {
        ("normalize", settings.registration_source): (
            *partitions(
                ctx, settings.registration_source, ["plate_codes", "plate_survey"]
            ),
            f"{ctx.config.paths.normalized}/{settings.registration_source}/manifest.json",
        )
    }
    parents = set(reads)
    source = ctx.config.sources.get(settings.plate_country_source)
    if source is not None and source.enabled:
        parents.add(("normalize", settings.plate_country_source))
    return Recipe(
        "plate_country", "world", dependencies=dependencies(parents, reads=reads)
    )
