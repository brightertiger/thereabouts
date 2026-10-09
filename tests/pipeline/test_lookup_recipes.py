"""Names and plate-country units follow configured roles, not source names."""

from pathlib import Path

import pytest

from pipeline.config import Config, load
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency
from pipeline.stages.engine_data import Geography
from pipeline.stages.engine_discovery import Discovery
from pipeline.stages.engine_recipes import lookup_recipes
from pipeline.stages.sources import PARTITIONS

from .helpers import context

NAMES = "engines.name_sources={geonames: [names, places], overture: [names]}"


def discovered(
    tmp_path: Path, config: Config, available: set[str]
) -> dict[str, list[Dependency]]:
    config.engines.countries = ["BE", "NL"]
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        ctx.config = config
        discovery = Discovery(available)
        discovery.load(ctx)
    return {
        f"{recipe.stage}/{recipe.unit_id}": list(recipe.dependencies)
        for recipes in discovery.recipes.values()
        for recipe in recipes
    }


def test_names_unit_reads_name_source_partitions_and_place_catalogues(
    tmp_path: Path,
) -> None:
    units = discovered(tmp_path, load(overrides=[NAMES]), {"plates"})
    assert units["lookups/names/world"] == [
        Dependency("normalize", "geonames", PARTITIONS),
        Dependency("normalize", "overture", PARTITIONS),
        Dependency("normalize_cells", "places/BE"),
        Dependency("normalize_cells", "places/NL"),
    ]
    assert Dependency("lookups", "names/world") in units["lookups/manifest/current"]
    assert "lookups/names/world" not in discovered(tmp_path, load(), {"plates"})


def test_plate_country_follows_the_registration_source(tmp_path: Path) -> None:
    config = load()
    registration = Dependency("normalize", "plates", PARTITIONS)
    units = discovered(tmp_path, config, {"plates"})
    assert units["plate_country/world"] == [registration]
    assert Dependency("plate_country", "world") in units["lookups/manifest/current"]
    config.sources["plate_country"].enabled = True
    assert discovered(tmp_path, config, {"plates"})["plate_country/world"] == [
        registration
    ]
    assert discovered(tmp_path, config, {"plates", "plate_country"})[
        "plate_country/world"
    ] == [Dependency("normalize", "plate_country"), registration]
    config.sources["plates"].enabled = False
    units = discovered(tmp_path, config, {"plates", "plate_country"})
    assert "plate_country/world" not in units
    assert Dependency("plate_country", "world") not in units["lookups/manifest/current"]


def test_name_sources_must_be_configured_with_kinds() -> None:
    with pytest.raises(ValueError, match="not configured"):
        load(overrides=["engines.name_sources={missing: [names]}"])
    with pytest.raises(ValueError, match="unique kinds"):
        load(overrides=["engines.name_sources={geonames: []}"])


def test_lookup_recipes_are_empty_without_countries(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        ctx.config = load(overrides=[NAMES])
        assert lookup_recipes(ctx, Geography([], {})) == []
