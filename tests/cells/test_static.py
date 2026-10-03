from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config.engines import EngineLimits
from pipeline.config.schema import H3
from pipeline.engines.cells.code_links import linked_rows
from pipeline.engines.cells.inputs import Inputs


def test_shared_phone_code_does_not_claim_unique_place_before_all_countries_ready(
    tmp_path: Path,
) -> None:
    path = tmp_path / "phone.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"prefix": "1", "country_codes": ["US", "CA"]},
                {"prefix": "999", "country_codes": ["ZZ"]},
            ]
        ),
        path,
    )
    inputs = Inputs({"US": {}}, {}, {}, {"US", "CA"}, grid=H3(), limits=EngineLimits())
    first = list(linked_rows(path, "phone_prefixes", inputs, {"US"}, {}))
    assert first[0]["link_status"] == "pending"
    assert first[0]["place_id"] is None
    assert first[0]["place_ids"] == ["country:US"]
    assert first[1]["link_status"] == "unmatched"
    inputs.countries["CA"] = {}
    ready = list(linked_rows(path, "phone_prefixes", inputs, {"US", "CA"}, {}))
    assert ready[0]["link_status"] == "ambiguous"
    assert ready[0]["country_id"] is None
    assert ready[0]["place_id"] is None
    assert ready[0]["place_ids"] == ["country:US", "country:CA"]


def test_subdivision_namespaces_and_non_geographic_phone_service(
    tmp_path: Path,
) -> None:
    path = tmp_path / "codes.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"country_code": "ZZ", "code": "ZZ.01", "code_system": "ISO 3166-2"},
                {"country_code": "ZZ", "code": "ZZ.01", "code_system": "GeoNames"},
            ]
        ),
        path,
    )
    inputs = Inputs({"ZZ": {}}, {}, {}, {"ZZ"}, grid=H3(), limits=EngineLimits())
    values = list(
        linked_rows(
            path,
            "subdivisions",
            inputs,
            {"ZZ"},
            {"iso:ZZ.01": {"state:iso"}, "geonames:ZZ.01": {"state:gn"}},
        )
    )
    assert [r["place_id"] for r in values] == ["state:iso", "state:gn"]
    pq.write_table(pa.Table.from_pylist([{"territory": "001"}]), path)
    service = next(linked_rows(path, "phone_metadata", inputs, {"ZZ"}, {}))
    assert service["link_status"] == "unmatched"
    assert service["place_ids"] == []
