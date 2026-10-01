"""Independent source predicates and builder snapshot guarantees."""

from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import Point

from build_data.normalize import features
from build_data.reference.oracle import Reference
from build_data.sources import acquire


def test_builder_rejects_cached_hash_mismatch_before_reading_source(
    tmp_path: Path,
) -> None:
    (tmp_path / "countries.zip").write_bytes(b"wrong archive")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        acquire(tmp_path)


@pytest.mark.world
def test_reference_matches_direct_source_polygons(world_path: Path) -> None:
    reference = Reference(Path("data/reference"))
    cache = Path("data/cache")
    if not all((cache / f"{layer}.zip").is_file() for layer in ("countries", "admin1")):
        pytest.skip("pinned source archives are required for the source oracle")
    rng = np.random.default_rng(810)
    points = [
        (float(lat), float(lon))
        for lat, lon in rng.uniform([-89, -180], [89, 180], (300, 2))
    ]
    points.extend([(50.85, 4.35), (52.7, 5.4), (-16.8, -180), (66, 179.9)])
    for layer in ("countries", "admin1"):
        source = []
        for row, geometry in features(cache / f"{layer}.zip"):
            if layer == "admin1" and ("+00?" in row["adm1_code"] or not row["name"]):
                continue
            identity = (
                f"ne:country:{row['NE_ID']}"
                if layer == "countries"
                else f"ne:admin1:{row['adm1_code']}"
            )
            source.append((identity, shapely.make_valid(geometry)))
        ids = np.array([identity for identity, _ in source])
        geometries = np.array([geometry for _, geometry in source], dtype=object)
        shapely.prepare(geometries)
        for lat, lon in points:
            point = Point(lon, lat)
            touching = shapely.intersects(geometries, point) | (
                shapely.distance(geometries, point) <= 1e-9
            )
            expected = set(ids[touching])
            if lon == -180:
                expected.update(ids[shapely.intersects(geometries, Point(180, lat))])
            rows = reference.admin.layers[
                "country" if layer == "countries" else layer
            ].query(lat, lon)
            table = reference.pack.arrays[layer]
            actual = {reference.pack.text(int(table[row]["id"])) for row in rows}
            assert actual == expected
    reference.close()


def test_settlement_ingestion_excludes_sections_and_former_places(
    tmp_path: Path,
) -> None:
    import zipfile

    from build_data.settlements import read_settlements

    codes = [
        "PPL",
        "PPLC",
        "PPLA5",
        "PPLF",
        "STLMT",
        "PPLX",
        "PPLH",
        "PPLQ",
        "PPLW",
        "PPLCH",
        "UNKNOWN",
    ]
    lines = []
    for identity, feature in enumerate(codes):
        fields = [
            str(identity),
            feature,
            "",
            "",
            "1",
            "2",
            "P",
            feature,
            "AA",
            "",
            "01",
            "",
            "",
            "",
            "1000",
            "",
            "",
            "UTC",
            "2026-10-01",
        ]
        lines.append("\t".join(fields))
    archive = tmp_path / "cities1000.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("cities1000.txt", "\n".join(lines))
    places = read_settlements(archive)
    assert [p.feature for p in places] == ["PPL", "PPLC", "PPLA5", "PPLF", "STLMT"]
