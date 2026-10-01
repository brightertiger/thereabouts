from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from build_data.acquire import Workspace
from build_data.golden.code_links import CodeIndex, linked_rows
from build_data.golden.inputs import Inputs
from build_data.reconcile.build import build_country
from build_data.reconcile.common import policy

from ..reconcile.conftest import area, write_inputs


def test_retained_district_aliases_join_without_guessing_ambiguous_names(
    tmp_path: Path,
) -> None:
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[],
        divisions=[],
        areas=[
            area("nation", "Nation", "country", (0, 0, 1, 1)),
            area("district", "Isère", "county", (0, 0, 0.3, 1)),
            area("one", "Central", "county", (0.3, 0, 0.6, 1)),
            area("two", "Central", "county", (0.6, 0, 1, 1)),
            area("unverified", "Unverified", "locality", (0.4, 0.4, 0.5, 0.5)),
        ],
    )
    output = build_country(Workspace(tmp_path), root, "ZZ", "inputs", policy(), "test")
    inputs = Inputs({"ZZ": {"path": str(output)}}, {}, {}, {}, "test", {"ZZ"})
    index = CodeIndex(inputs)
    path = tmp_path / "codes.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "country_code": "ZZ",
                    "code_system": "ISO-3166-2",
                    "code": code,
                    "name": name,
                }
                for code, name in [
                    ("ZZ-A", "Isere"),
                    ("ZZ-B", "Central"),
                    ("ZZ-C", "Unknown"),
                    ("ZZ-D", "Unverified"),
                ]
            ]
        ),
        path,
    )
    linked = list(
        linked_rows(
            path, "subdivisions", inputs, index.countries, index.codes, index=index
        )
    )
    assert [r["link_status"] for r in linked] == [
        "matched",
        "ambiguous",
        "unmatched",
        "unmatched",
    ]
    assert linked[0]["place_id"] == "district:overture:district"
    assert linked[1]["place_id"] is None
    assert len(linked[1]["place_ids"]) == 2
    assert linked[0]["code"] == "ZZ-A"
