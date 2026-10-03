"""Exhaustive old-stage to new-unit mapping. Unknown stages stop adoption."""

from dataclasses import dataclass

from pipeline.runtime.jsonio import Object

from .inventory import Inventory

# These are migration rules, not runtime source discovery or engine aliases.
SOURCE_ACTIONS = {
    "download": "download",
    "normalize": "normalize",
    "manifest": "normalize",
    "audit": "normalize",
}
ENGINE_ACTIONS = {
    "reconcile.extract": ("reconcile", "extract"),
    "reconcile.links": ("reconcile", "links"),
    "reconcile.country": ("reconcile", "country"),
    "reconcile.land": ("reconcile", "land"),
    "reconcile.quality": ("reconcile", "quality"),
    "reconcile.gate": ("reconcile", "gate"),
    "reconcile.manifest": ("reconcile", "manifest"),
    "golden.plan": ("cells", "plan"),
    "golden.cells": ("cells", "block"),
    "golden.places": ("cells", "places"),
    "golden.manifest": ("cells", "manifest"),
    "golden.static": ("lookups", "static"),
    "cities.country": ("cities", "country"),
    "cities.mapping": ("cities", "mapping"),
    "cities.manifest": ("cities", "manifest"),
    "normalize-cells.cells": ("normalize_cells", "block"),
    "normalize-cells.places": ("normalize_cells", "places"),
    "normalize-cells.quality": ("normalize_cells", "quality"),
    "normalize-cells.lookup": ("lookups", "spatial"),
}
RETIRED = {
    "golden.lookup": "superseded joins; active joins belong to lookups",
    "golden-v2.cells": "superseded pilot implementation",
    "golden-v2.places": "superseded pilot implementation",
}
AUXILIARY_NORMALIZE = {"geonames.extract", "geonames.index", "overture.index"}


@dataclass(frozen=True)
class Mapping:
    stage: str | None
    unit_id: str
    reason: str


def destination(
    inventory: Inventory,
    stage: str,
    unit_id: str,
    outputs: list[Object],
) -> Mapping:
    if stage in RETIRED:
        return Mapping(None, unit_id, RETIRED[stage])
    source, _, action = stage.partition(".")
    if source in inventory.sources:
        if stage in AUXILIARY_NORMALIZE:
            return Mapping(
                "normalize", source, "retained auxiliary normalization output"
            )
        if action in SOURCE_ACTIONS:
            return Mapping(SOURCE_ACTIONS[action], source, "aggregate source unit")
        if stage == "osm_land.index":
            return Mapping("normalize", source, "retained normalized spatial index")
    if stage == "base-cells.snapshot":
        if unit_id == inventory.base_pointer.get("digest"):
            return Mapping("cells", "snapshot/current", "selected immutable base")
        return Mapping(None, unit_id, "superseded base snapshot")
    if stage in ENGINE_ACTIONS:
        target, action = ENGINE_ACTIONS[stage]
        if stage.startswith("normalize-cells."):
            output = inventory.output(outputs[0])
            if not output.path.startswith(inventory.active_prefix + "/"):
                return Mapping(None, unit_id, "superseded or pilot normalization")
            unit_id = unit_id.rsplit(":", 1)[-1]
        return Mapping(target, f"{action}/{unit_id}", "retained engine output")
    raise ValueError(f"No adoption mapping for {stage}/{unit_id}")
