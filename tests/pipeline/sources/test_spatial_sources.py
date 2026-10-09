"""Ports regenerate their auxiliaries and retain key source conversion decisions."""

import json
from pathlib import Path
from typing import Any

import shapely

from pipeline.runtime.ledger import Ledger
from pipeline.runtime.runner import run

from .fixtures import (
    alternate,
    archive,
    division,
    feature,
    parquet,
    rows,
    source_context,
)


def test_geonames_regenerates_caches_and_preserves_reject_accounting(
    tmp_path: Path,
) -> None:
    payloads: dict[str, tuple[bytes, dict[str, Any]]] = {
        "allCountries.zip": (
            archive(
                {
                    "allCountries.txt": feature(1)
                    + feature(2, "A", "ADM4")
                    + feature(3, "T", "MT")
                    + feature(1)
                    + b"bad\n"
                }
            ),
            {},
        ),
        "alternateNamesV2.zip": (
            archive(
                {
                    "alternateNamesV2.txt": alternate(10, 1, "Current")
                    + alternate(11, 1, "Old", "1")
                    + alternate(12, 999)
                    + alternate(10, 1)
                    + b"bad\n"
                }
            ),
            {},
        ),
    }
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(tmp_path, ledger, "geonames", payloads)
        assert run(source.runtime, stages) == {"completed": 2, "skipped": 0}
        points, aliases = rows(source, "places"), rows(source, "names")
        assert len(points) == 2 and len(aliases) == 2
        assert points[0]["name"] == "Café" and points[0]["name_en"] == "Current"
        assert aliases[1]["is_historic"]
        record = ledger.get("normalize", "geonames")
        assert record
        # Regenerable caches are not recorded, so deleting one restores nothing.
        assert not [item for item in record.outputs if "/work/" in f"/{item.path}"]
        cache = next(source.work.rglob("lookup.sqlite3"))
        cache.unlink()
        assert run(source.runtime, stages) == {"completed": 0, "skipped": 2}
        audit = json.loads(
            next((source.normalized / "audits").rglob("report.json")).read_bytes()
        )
        assert audit["inputs"][0]["counts"] == {
            "input": 5,
            "kept": 2,
            "excluded": 1,
            "rejected": 2,
        }
        assert audit["inputs"][1]["counts"] == {
            "input": 5,
            "kept": 2,
            "excluded": 1,
            "rejected": 2,
        }
        assert run(source.runtime, stages) == {"completed": 0, "skipped": 2}


def test_overture_regenerates_parent_index_before_areas(tmp_path: Path) -> None:
    area = {
        "id": "area",
        "division_id": "point",
        "geometry": shapely.box(2, 1, 3, 2).wkb,
        "names": {"primary": "Area", "common": {"en": "Area"}},
        "subtype": "locality",
        "admin_level": 3,
        "country": "US",
        "region": "US-NY",
        "is_land": True,
        "is_territorial": True,
    }
    with Ledger(tmp_path, None, readonly=False) as ledger:
        source, stages = source_context(
            tmp_path,
            ledger,
            "overture",
            {
                "divisions.parquet": (parquet([division()]), {"type": "division"}),
                "areas.parquet": (parquet([area]), {"type": "division_area"}),
            },
        )
        run(source.runtime, stages)
        assert len(rows(source, "places")) == 1 and len(rows(source, "names")) == 2
        assert rows(source, "areas")[0]["parent_source_id"] == "parent"
        record = ledger.get("normalize", "overture")
        assert record
        assert not [i for i in record.outputs if i.path.endswith("entities.sqlite3")]
        index = next(source.work.rglob("entities.sqlite3"))
        index.write_bytes(b"corrupt cache")
        ledger.invalidate("normalize", ["overture"])
        assert run(source.runtime, stages) == {"completed": 1, "skipped": 1}
        assert index.read_bytes().startswith(b"SQLite format 3")
