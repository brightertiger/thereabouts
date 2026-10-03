"""Tiny normalized inputs; all reconciliation tests run entirely offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from pipeline.sources.shared.schemas import SCHEMAS, Kind


def place(
    identity: str,
    name: str,
    x: float,
    y: float,
    *,
    source: str = "geonames",
    code: str = "PPL",
    subtype: str = "locality",
    population: int = 100,
    qid: str | None = None,
    country: str = "ZZ",
) -> dict[str, Any]:
    provenance = {
        "source_url": "https://example.test",
        "license_url": "https://example.test/license",
        "attribution": "test",
        "upstream": {"wikidata": qid},
        "asciiname": name,
    }
    return {
        "source": source,
        "source_id": identity,
        "kind": subtype,
        "name": name,
        "name_en": name,
        "latitude": y,
        "longitude": x,
        "feature_class": "A" if code.startswith("ADM") else "P",
        "feature_code": code if source == "geonames" else None,
        "subtype": subtype,
        "country_code": country,
        "admin1_code": "01",
        "admin2_code": None,
        "parent_source_id": None,
        "population": population,
        "source_release": "test",
        "license": "CC BY 4.0",
        "provenance": json.dumps(provenance),
    }


def area(
    identity: str,
    name: str,
    subtype: str,
    bounds: tuple[float, float, float, float],
    *,
    source: str = "overture",
    country: str = "ZZ",
    level: str | None = None,
) -> dict[str, Any]:
    geometry = shapely.box(*bounds)
    return {
        "source": source,
        "source_id": identity + "-area",
        "entity_id": identity,
        "kind": subtype,
        "subtype": subtype,
        "admin_level": level,
        "parent_source_id": None,
        "country_code": country,
        "subdivision_code": country + "-01",
        "name": name,
        "name_en": name,
        "geometry": geometry.wkb,
        "xmin": bounds[0],
        "ymin": bounds[1],
        "xmax": bounds[2],
        "ymax": bounds[3],
        "is_land": True,
        "is_territorial": True,
        "source_release": "test",
        "license": "CC BY 4.0",
        "provenance": json.dumps(
            {
                "source_url": "https://example.test",
                "license_url": "https://example.test/license",
                "attribution": "test",
            }
        ),
    }


def write_inputs(
    root: Path,
    *,
    geonames: list[dict[str, Any]],
    divisions: list[dict[str, Any]],
    areas: list[dict[str, Any]],
    boundaries: list[dict[str, Any]] | None = None,
    names: list[dict[str, Any]] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, kind, values in (
        ("geonames_places", "places", geonames),
        ("overture_places", "places", divisions),
        ("overture_areas", "areas", areas),
        ("geoboundaries_areas", "areas", boundaries or []),
        ("geonames_names", "names", names or []),
    ):
        schema_kind: Kind = kind  # type: ignore[assignment]
        pq.write_table(
            pa.Table.from_pylist(values, schema=SCHEMAS[schema_kind]),
            root / f"{name}.parquet",
        )
    return root


def reconciled(
    workspace: Path, extracted: Path, country: str, policy: dict[str, Any]
) -> Path:
    from pipeline.config.engines import EngineLimits
    from pipeline.engines.reconcile.build import build_country
    from pipeline.engines.reconcile.catalog import catalog

    limits = EngineLimits()
    linked = catalog(
        extracted, workspace / "work" / f"{country}-links.sqlite", policy, limits
    )
    return build_country(
        linked,
        extracted,
        workspace / "reconciled" / f"{country}.sqlite",
        country,
        policy,
        limits,
    )
