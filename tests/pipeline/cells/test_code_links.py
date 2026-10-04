from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config.engines import EngineLimits
from pipeline.config.policies import reconcile as policy
from pipeline.config.schema import H3
from pipeline.engines.cells.code_links import CodeIndex, linked_rows
from pipeline.engines.cells.inputs import Inputs
from tests.pipeline.reconciliation.conftest import reconciled

from ..reconciliation.conftest import area, place, write_inputs


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
    output = reconciled(tmp_path, root, "ZZ", policy())
    inputs = Inputs(
        {"ZZ": {"path": str(output)}}, {}, {}, {"ZZ"}, grid=H3(), limits=EngineLimits()
    )
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


def test_subdivision_can_identify_a_separately_represented_territory(
    tmp_path: Path,
) -> None:
    configured = policy() | {"sovereigns": {"YY": ["ZZ", "Nation"]}}
    paths = {}
    for cc in ("ZZ", "YY", "XX"):
        shape = area(cc, cc, "country", (0, 0, 1, 1))
        shape["country_code"] = cc
        root = write_inputs(tmp_path / cc, geonames=[], divisions=[], areas=[shape])
        output = reconciled(tmp_path, root, cc, configured)
        paths[cc] = {"path": str(output)}
    index = CodeIndex(Inputs(paths, {}, {}, grid=H3(), limits=EngineLimits()))
    matched, _ = index.subdivision(
        {"country_code": "ZZ", "code_system": "ISO-3166-2", "code": "ZZ-YY"}
    )
    unrelated, _ = index.subdivision(
        {"country_code": "ZZ", "code_system": "ISO-3166-2", "code": "ZZ-XX"}
    )
    assert matched == ["country:YY"]
    assert unrelated == []


def test_source_qualified_aliases_preserve_type_scope_and_ambiguity(
    tmp_path: Path,
) -> None:
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[],
        divisions=[],
        areas=[
            area("nation", "Nation", "country", (0, 0, 1, 1)),
            area("river", "River District", "county", (0, 0, 1, 1)),
            area("north", "District North", "county", (0, 0, 1, 1)),
            area("island", "Island", "county", (0, 0, 1, 1)),
            area("one", "Central District", "county", (0, 0, 1, 1)),
            area("two", "Central District", "county", (0, 0, 1, 1)),
            area("weak", "Weak District", "locality", (0, 0, 1, 1)),
        ],
    )
    output = reconciled(tmp_path, root, "ZZ", policy())
    inputs = Inputs(
        {"ZZ": {"path": str(output)}}, {}, {}, {"ZZ"}, grid=H3(), limits=EngineLimits()
    )
    index = CodeIndex(inputs)
    path = tmp_path / "codes.parquet"
    cases = [
        ("River", "District", "matched", "district:overture:river"),
        ("North", "District", "matched", "district:overture:north"),
        ("Island [Alternative ZZ-I1]", None, "matched", "district:overture:island"),
        ("Alternative [Island ZZ-I1]", None, "matched", "district:overture:island"),
        ("Alternative [Island YY-I1]", None, "unmatched", None),
        ("River", "Province", "unmatched", None),
        ("Rivers", "District", "unmatched", None),
        ("Central", "District", "ambiguous", None),
        ("Weak", "District", "unmatched", None),
    ]
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "country_code": "ZZ",
                    "code_system": "ISO-3166-2",
                    "code": f"ZZ-{number}",
                    "name": name,
                    "type": kind,
                }
                for number, (name, kind, _, _) in enumerate(cases)
            ]
        ),
        path,
    )
    linked = list(
        linked_rows(
            path, "subdivisions", inputs, index.countries, index.codes, index=index
        )
    )
    assert [(r["link_status"], r["place_id"]) for r in linked] == [
        (status, identity) for _, _, status, identity in cases
    ]
    assert len(linked[7]["place_ids"]) == 2
    assert linked[0]["link_method"] == "source-qualified administrative alias"


def test_geonames_admin1_codes_link_through_the_state_crosswalk(
    tmp_path: Path,
) -> None:
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[place("3", "State", 0.5, 0.5, code="ADM1")],
        divisions=[place("s", "State", 0.5, 0.5, source="overture", subtype="region")],
        areas=[
            area("country", "Country", "country", (0, 0, 2, 2)),
            area("s", "State", "region", (0, 0, 2, 2)),
        ],
    )
    output = reconciled(tmp_path, root, "ZZ", policy())
    inputs = Inputs(
        {"ZZ": {"path": str(output)}}, {}, {}, {"ZZ"}, grid=H3(), limits=EngineLimits()
    )
    index = CodeIndex(inputs)
    path = tmp_path / "codes.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "country_code": "ZZ",
                    "code_system": "GeoNames-admin1",
                    "code": code,
                    "name": name,
                    "name_ascii": name,
                    "geoname_id": geoname_id,
                }
                for code, name, geoname_id in [
                    ("ZZ.01", "Renamed", "999"),
                    ("ZZ.99", "Nowhere", "998"),
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
    assert [r["link_status"] for r in linked] == ["matched", "unmatched"]
    assert linked[0]["link_method"] == "explicit code or administrative crosswalk"
    assert linked[0]["place_id"] == "state:overture:s"
