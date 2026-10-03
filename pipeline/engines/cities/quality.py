"""Regenerated footprint, urban-centre, neighbour and named-point censuses."""

import json

import h3
import shapely

from pipeline.engines.artifacts import EVALUATION
from pipeline.engines.cells.inputs import Inputs
from pipeline.engines.cells.quality import display_names
from pipeline.engines.reconcile.common import Row, connect

from .boundary_checks import boundary_checks
from .diagnostic import checks
from .engine import Engine
from .evaluate import Comparison, measure
from .regressions import audit
from .urban import Urban


def footprint_checks(comparison: Comparison, cc: str, engine: Engine) -> list[Row]:
    result = []
    large = {r["city_id"] for r in engine.cities if r["population"] >= 100000}
    for fp in engine.footprints:
        if fp["city_id"] not in large:
            continue
        cells = sorted(
            h3.geo_to_cells(
                fp["geometry"].__geo_interface__, comparison.before.grid.cell_resolution
            )
        )
        before, after = comparison.query(cells)
        # Border/coastal membership is tested only for eligible same-country cells.
        chosen = [
            i for i, r in enumerate(before) if r.get("country_id") == f"country:{cc}"
        ]
        result.append(
            {
                "city_id": fp["city_id"],
                "method": fp["method"],
                "before": measure([before[i] for i in chosen], fp["city_id"]),
                "after": measure([after[i] for i in chosen], fp["city_id"]),
            }
        )
    return result


def urban_checks(
    comparison: Comparison, cc: str, engine: Engine, urban: Urban
) -> list[Row]:
    db = connect(engine.source, readonly=True, cache_kib=engine.limits.sqlite_cache_kib)
    try:
        borders = [
            shapely.from_wkb(b)
            for (b,) in db.execute("SELECT geometry FROM areas WHERE role='country'")
        ]
        tree = shapely.STRtree(borders)
        indices = {
            int(i) for i, shape in enumerate(urban.shapes) if len(tree.query(shape))
        }
    finally:
        db.close()
    result = []
    for index in sorted(indices):
        cells = sorted(
            h3.geo_to_cells(
                urban.shapes[index].__geo_interface__,
                comparison.before.grid.cell_resolution,
            )
        )
        before, after = comparison.query(cells)
        chosen = [
            i for i, r in enumerate(before) if r.get("country_id") == f"country:{cc}"
        ]
        if chosen:
            result.append(
                {
                    "urban_id": urban.ids[index],
                    "before": measure([before[i] for i in chosen]),
                    "after": measure([after[i] for i in chosen]),
                }
            )
    return result


def neighbour_checks(
    comparison: Comparison, cc: str, engine: Engine, probes: Row
) -> list[Row]:
    by_id = {r["city_id"]: r for r in engine.cities}
    result = []
    for identity, name in probes.get(cc, {}).items():
        city = by_id.get(identity)
        if city is None:
            result.append(
                {"city_id": identity, "name": name, "error": "missing canonical city"}
            )
            continue
        cell = h3.latlng_to_cell(
            city["latitude"], city["longitude"], comparison.before.grid.cell_resolution
        )
        before, after = comparison.query([cell])
        patch = sorted(h3.grid_disk(cell, 4))
        pb, pa = comparison.query(patch)
        # Inspect original source polygons even if normalization rejected them.
        # Otherwise rejecting a town's footprint could hide the very regression
        # this independent neighbour check is meant to expose.
        db = connect(
            engine.source, readonly=True, cache_kib=engine.limits.sqlite_cache_kib
        )
        try:
            source_areas = db.execute(
                "SELECT id,geometry FROM areas WHERE entity=? AND role='city'",
                (identity,),
            ).fetchall()
        finally:
            db.close()
        owned = sorted(
            {
                c
                for _, blob in source_areas
                for c in h3.geo_to_cells(
                    shapely.from_wkb(blob).__geo_interface__,
                    comparison.before.grid.cell_resolution,
                )
            }
        )
        ob, oa = comparison.query(owned)
        result.append(
            {
                "city_id": identity,
                "name": name,
                "source_area_ids": [r[0] for r in source_areas],
                "accepted_city_footprint": any(
                    f["city_id"] == identity for f in engine.footprints
                ),
                "point_before": before[0],
                "point_after": after[0],
                "patch_before": measure(pb, identity),
                "patch_after": measure(pa, identity),
                "polygon_before": measure(ob, identity),
                "polygon_after": measure(oa, identity),
                "patch_losses": [
                    {
                        "h3": c,
                        "latitude": h3.cell_to_latlng(c)[0],
                        "longitude": h3.cell_to_latlng(c)[1],
                        "after": a,
                    }
                    for c, b, a in zip(patch, pb, pa, strict=True)
                    if b.get("city_id") == identity and a.get("city_id") != identity
                ],
            }
        )
    return result


def named_checks(comparison: Comparison, inputs: Inputs) -> list[Row]:
    probes = json.loads((EVALUATION / "cities/probes.json").read_text())["named"]
    fixtures = json.loads((EVALUATION / "reconcile/fixtures.json").read_text())
    result = []
    for label, lat, lon, cc, target, *_ in [*probes, *fixtures]:
        before, after = comparison.query(
            [h3.latlng_to_cell(lat, lon, comparison.before.grid.cell_resolution)]
        )
        names = display_names(inputs, after[0])
        passed = (
            after[0].get("city_id") == target
            if target.startswith("city:")
            else names.get("city") == target
        )
        result.append(
            {
                "label": label,
                "country": cc,
                "latitude": lat,
                "longitude": lon,
                "expected": target,
                "before": before[0],
                "after": {**after[0], **names},
                "passed": passed and after[0].get("country_id") == f"country:{cc}",
            }
        )
    return result


def country_report(
    comparison: Comparison, cc: str, engine: Engine, urban: Urban, probes: Row
) -> Row:
    return {
        "diagnostic": checks(comparison, engine),
        "plan_regressions": audit(comparison, cc, engine),
        "footprints": footprint_checks(comparison, cc, engine),
        "all_boundaries": boundary_checks(comparison, cc, engine),
        "neighbours": neighbour_checks(comparison, cc, engine, probes["neighbours"]),
        "urban_centres": urban_checks(comparison, cc, engine, urban),
    }
