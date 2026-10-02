"""Regenerated footprint, urban-centre, neighbour and named-point censuses."""

import json
from pathlib import Path

import h3

from build_data.golden.inputs import Inputs
from build_data.golden.quality import display_names
from build_data.reconcile.common import Row, connect

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
        cells = sorted(h3.geo_to_cells(fp["geometry"].__geo_interface__, 8))
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
    db = connect(engine.source, readonly=True)
    try:
        import shapely

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
        cells = sorted(h3.geo_to_cells(urban.shapes[index].__geo_interface__, 8))
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
        cell = h3.latlng_to_cell(city["latitude"], city["longitude"], 8)
        before, after = comparison.query([cell])
        patch = sorted(h3.grid_disk(cell, 4))
        pb, pa = comparison.query(patch)
        polygons = [f for f in engine.footprints if f["city_id"] == identity]
        owned = sorted(
            {
                c
                for fp in polygons
                for c in h3.geo_to_cells(fp["geometry"].__geo_interface__, 8)
            }
        )
        ob, oa = comparison.query(owned)
        result.append(
            {
                "city_id": identity,
                "name": name,
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
    probes = json.loads(Path(__file__).with_name("probes.json").read_text())["named"]
    fixtures = json.loads(
        (Path(__file__).parents[1] / "reconcile/fixtures.json").read_text()
    )
    result = []
    for label, lat, lon, cc, target, *_ in [*probes, *fixtures]:
        before, after = comparison.query([h3.latlng_to_cell(lat, lon, 8)])
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
    from .diagnostic import checks

    return {
        "diagnostic": checks(comparison, engine),
        "plan_regressions": audit(comparison, cc, engine),
        "footprints": footprint_checks(comparison, cc, engine),
        "neighbours": neighbour_checks(comparison, cc, engine, probes["neighbours"]),
        "urban_centres": urban_checks(comparison, cc, engine, urban),
    }
