from __future__ import annotations

from pathlib import Path

from pipeline.config.engines import EngineLimits
from pipeline.config.policies import reconcile as policy
from pipeline.engines.store.codec import unpack
from pipeline.engines.store.database import connect
from tests.pipeline.reconciliation.conftest import reconciled

from .conftest import area, place, write_inputs


def test_division_english_name_survives_blank_area_name(tmp_path: Path) -> None:
    state = area("state", "Local spelling", "region", (0, 0, 1, 1))
    state["name_en"] = None
    root = write_inputs(
        tmp_path / "in",
        geonames=[],
        divisions=[
            place(
                "state",
                "English spelling",
                0.5,
                0.5,
                source="overture",
                subtype="region",
            ),
        ],
        areas=[area("country", "Country", "country", (0, 0, 1, 1)), state],
    )
    path = reconciled(tmp_path, root, "ZZ", policy())
    db = connect(path, readonly=True, cache_kib=EngineLimits().sqlite_cache_kib)
    try:
        entity = unpack(
            db.execute("SELECT data FROM entities WHERE role='state'").fetchone()[0]
        )
        assert entity["name"] == "English spelling"
        assert entity["local_name"] == "Local spelling"
        assert entity["name_provenance"]["source"] == "overture"
    finally:
        db.close()


def test_gb_whole_layer_and_ph_province_equivalent_city(tmp_path: Path) -> None:
    for cc in ("GB", "PH"):
        region = place(
            "r",
            "Planning region",
            0.5,
            0.5,
            source="overture",
            subtype="region",
            country=cc,
        )
        city = place("c", "Independent city", 0.5, 0.5, source="overture", country=cc)
        city["parent_source_id"] = "r"
        root = write_inputs(
            tmp_path / cc,
            geonames=[],
            divisions=[region, city],
            areas=[
                area("nation", "Nation", "country", (0, 0, 1, 1), country=cc),
                area("r", "Planning region", "region", (0, 0, 1, 1), country=cc),
                area("county", "Province", "county", (0, 0, 0.4, 1), country=cc),
                area("c", "Independent city", "locality", (0.4, 0, 1, 1), country=cc),
            ],
            boundaries=[
                area(
                    "s",
                    "Constituent country",
                    "administrative",
                    (0, 0, 1, 1),
                    source="geoboundaries",
                    country=cc,
                    level="ADM1",
                )
            ],
        )
        selected = policy()
        selected["rollups"] = []
        path = reconciled(tmp_path, root, cc, selected)
        db = connect(path, readonly=True, cache_kib=EngineLimits().sqlite_cache_kib)
        try:
            states = {
                unpack(r[0])["name"]
                for r in db.execute("SELECT data FROM entities WHERE role='state'")
            }
            assert states == (
                {"Constituent country"}
                if cc == "GB"
                else {"Province", "Independent city"}
            )
        finally:
            db.close()
