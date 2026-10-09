"""Spatial subsets preserve coarse timezone membership and missing coordinates."""

import pyarrow as pa
from h3.api import basic_int as h3

from pipeline.config.schema import H3
from pipeline.release.selection import Selection


def test_fine_coarse_outside_and_unlocated_rows() -> None:
    key = h3.latlng_to_cell(3.139, 101.6869, 8)
    block = h3.cell_to_parent(key, 3)
    keys = [key, h3.cell_to_parent(key, 0), h3.latlng_to_cell(50, 0, 8), None]
    batch = pa.record_batch(
        {
            "h3_uint64": pa.array(keys, type=pa.uint64()),
            "h3_resolution": pa.array([8, 0, 8, None], type=pa.uint8()),
            "country_code": ["MY"] * 4,
        }
    )
    select = Selection(("MY",), (f"{block:x}",), H3())
    assert select.filter("timezone_cells", batch).column(0).to_pylist() == keys[:2]
    assert select.filter("airports", batch).column(0).to_pylist() == [*keys[:2], None]


def test_country_subsets_filter_names_and_plates_but_keep_the_policy() -> None:
    select = Selection(("MY",), (f"{h3.latlng_to_cell(3.1, 101.7, 3):x}",), H3())
    rows = pa.record_batch({"city_id": ["a", "b"], "country_code": ["MY", "FR"]})
    for kind in ("names", "plate_formats", "plate_codes", "plate_priors"):
        assert select.filter(kind, rows).column(0).to_pylist() == ["a"]
    policy = pa.record_batch({"policy_json": ["{}"]})
    assert select.filter("plate_policy", policy).num_rows == 1
