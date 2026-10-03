"""Reconstruct the actual source/country/block inputs read by the old engines."""

from pipeline.runtime.records import Dependency

from .candidates import Candidate


def dependencies(
    candidate: Candidate,
    candidates: dict[tuple[str, str], Candidate],
    groups: dict[tuple[str, str], tuple[tuple[str, str], ...]],
) -> tuple[Dependency, ...]:
    stage, unit = candidate.key
    action, _, key = unit.partition("/")
    keys: set[tuple[str, str]] = set()

    def group(name: str, prefix: str = "") -> None:
        selection = name, prefix
        if selection not in groups:
            groups[selection] = tuple(
                k for k in candidates if k[0] == name and k[1].startswith(prefix)
            )
        keys.update(groups[selection])

    if stage == "normalize":
        keys.add(("download", unit))
    elif stage == "reconcile":
        if action == "extract":
            keys.update(
                ("normalize", source)
                for source in ("overture", "geonames", "geoboundaries")
            )
        elif action == "land":
            keys.add(("normalize", "osm_land"))
        elif action == "links":
            keys.add((stage, "extract/" + key))
        elif action == "country":
            keys.update((stage, f"{item}/{key}") for item in ("extract", "links"))
        elif action == "quality":
            keys.update({(stage, "country/" + key), (stage, "land/world")})
        elif action in {"gate", "manifest"}:
            group(stage, "country/")
            group(stage, "quality/")
            keys.add((stage, "land/world"))
    elif stage == "cells":
        if action in {"block", "places", "plan"}:
            countries = candidate.countries if action == "block" else [key]
            if action == "plan":
                group("reconcile", "country/")
            else:
                keys.update(("reconcile", "country/" + cc) for cc in countries)
            keys.add(("reconcile", "land/world"))
        elif action == "manifest":
            group(stage, "block/")
            group(stage, "places/")
        elif action == "snapshot":
            group(stage, "manifest/")
    elif stage == "cities":
        if action == "country":
            keys.update({("reconcile", "country/" + key), ("normalize", "ghsl")})
        elif action == "mapping":
            keys.update({(stage, "country/" + key), ("reconcile", "country/" + key)})
        else:
            group(stage, "country/")
            group(stage, "mapping/")
    elif stage == "evaluate":
        group("cities", "manifest/")
        group("cells", "snapshot/")
    elif stage == "normalize_cells":
        if action == "block":
            base = candidates["cells", "block/" + key]
            keys.add(base.key)
            for cc in base.countries:
                keys.update(
                    {("cities", "country/" + cc), ("reconcile", "country/" + cc)}
                )
            keys.add(("reconcile", "land/world"))
            keys.add(("normalize", "ghsl"))
        elif action == "places":
            keys.update(
                {
                    ("cells", "places/" + key),
                    ("cities", "mapping/" + key),
                    ("cities", "country/" + key),
                }
            )
        elif action == "quality":
            keys.update(
                k
                for k, c in candidates.items()
                if k[0] == "cells" and k[1].startswith("block/") and key in c.countries
            )
            keys.update(("normalize_cells", k[1]) for k in tuple(keys))
            keys.add(("cities", "country/" + key))
            keys.add(("reconcile", "country/" + key))
        group("evaluate")
    elif stage == "lookups":
        if action == "static":
            # Static joins read place identities and the relevant normalized source.
            kind = key.split("/")[0]
            source = {
                "countries": "codes",
                "subdivisions": "codes",
                "phone_prefixes": "phone",
                "phone_metadata": "phone",
                "timezone_cells": "timezones",
                "zone_tables": "timezones",
            }[kind]
            keys.add(("normalize", source))
            if source != "timezones":
                group("cells", "places/")
        elif action == "spatial":
            source = {
                "airports": "airports",
                "postal_codes": "postal",
                "ip_ranges": "dbip",
                "trade_locations": "unlocode",
            }[key]
            keys.add(("normalize", source))
            group("normalize_cells", "block/")
        else:
            group("normalize_cells")
            group(stage, "static/")
            group(stage, "spatial/")
    absent = keys.difference(candidates)
    if absent:
        raise ValueError(
            f"Unmapped upstream units for {candidate.key}: {sorted(absent)}"
        )
    return tuple(Dependency(*key) for key in sorted(keys))
