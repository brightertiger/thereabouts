"""Share independent source and spatial inventories across geographic stages."""

from dataclasses import asdict

from pipeline.runtime.jsonio import digest
from pipeline.runtime.paths import located
from pipeline.runtime.records import Dependency, Recipe

from .contract import Context
from .engine_data import Geography, geography
from .engine_recipes import geographic_recipes, lookup_recipes


class Discovery:
    def __init__(self) -> None:
        self.stamp: str | None = None
        self.geography = Geography([], {})
        self.recipes: dict[str, list[Recipe]] = {}

    def load(self, ctx: Context) -> None:
        settings = ctx.config.engines
        files = [
            *sorted(
                located(ctx.root, ctx.config.paths.normalized).glob("*/manifest.json")
            ),
            located(ctx.root, settings.block_index),
            located(ctx.root, settings.retained_block_index),
        ]
        stamp = digest(
            {
                "root": str(ctx.root),
                "settings": asdict(settings),
                "h3": asdict(ctx.config.h3),
                "files": [
                    (str(p), p.stat().st_size, p.stat().st_mtime_ns)
                    for p in files
                    if p.is_file()
                ],
                "overlay": id(ctx.verifier.overlay),
            }
        )
        if stamp == self.stamp:
            return
        self.geography = geography(ctx)
        self.recipes = {}
        for recipe in geographic_recipes(ctx, self.geography) + lookup_recipes(
            ctx, self.geography
        ):
            self.recipes.setdefault(recipe.stage, []).append(recipe)
        source = ctx.config.sources.get("plate_country")
        if source is not None and source.enabled:
            self.recipes["plate_country"] = [
                Recipe(
                    "plate_country",
                    "world",
                    dependencies=(
                        Dependency("normalize", "plate_country"),
                        Dependency("normalize", "plates"),
                    ),
                )
            ]
        self.stamp = stamp
