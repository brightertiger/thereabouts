from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import shapely
from h3.api import basic_int as h3

from build_data.golden.planning import Dependencies
from build_data.golden.seam import oracle
from build_data.golden.windows import envelopes
from build_data.hierarchy import descendants, label_block
from build_data.reconcile.common import connect, pack
from build_data.reconcile.lookup import Locator
from build_data.reconcile.spatial import insert_area


@pytest.mark.parametrize("latitude", [0, 90, -90])
def test_seam_and_poles_match_every_scalar_centre(
    synthetic: tuple[Locator, dict[str, Path]], latitude: int
) -> None:
    original, paths = synthetic
    land_path = paths["ZZ"].with_name("land.sqlite")
    for path, role in ((paths["ZZ"], "country"), (land_path, "land")):
        db = connect(path)
        try:
            db.execute("DELETE FROM area_bounds")
            db.execute("DELETE FROM areas")
            shapes = (
                [shapely.box(-180, -90, 180, 90)]
                if latitude
                else [
                    shapely.box(179.5, -1, 179.995 if role == "land" else 180, 1),
                    shapely.box(-180, -1, -179.5, 1),
                ]
            )
            for shape in shapes:
                insert_area(
                    db,
                    "country:ZZ",
                    role,
                    0,
                    shape.wkb,
                    shape.bounds,
                    pack({"source": "test", "source_id": "seam"}),
                )
            db.commit()
        finally:
            db.close()
    cells, coordinates = descendants(h3.latlng_to_cell(latitude, 179.99, 3), 8)
    with Locator(paths, land_path, original.policy) as scalar:
        reference = oracle(scalar, paths, coordinates)
        labels = label_block(reference, cells, coordinates, 8)
        assert np.array_equal(labels, reference.labels(coordinates))
        for point, value in zip(coordinates, labels, strict=True):
            answer = scalar.locate(*point)
            expected = (
                *(
                    answer[k]["id"] if answer[k] else None
                    for k in ("country", "state", "city")
                ),
                answer["city_method"],
                answer["land_method"],
            )
            assert reference.answers[int(value)] == expected


def test_seam_dependencies_do_not_wait_for_a_country_on_the_opposite_meridian() -> None:
    _, coordinates = descendants(h3.latlng_to_cell(0, 179.99, 3), 8)
    dependencies = Dependencies(
        {
            "bounds": [
                ("EE", 179, -2, 180, 2),
                ("WW", -180, -2, -179, 2),
                ("XX", -1, -2, 1, 2),
            ]
        },
        1000,
    )
    required = {c for b in envelopes(coordinates) for c in dependencies.countries(b)}
    assert required == {"EE", "WW"}
