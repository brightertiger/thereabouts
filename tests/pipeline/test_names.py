"""Canonical-city alternate names: links, filters, kinds and stable output."""

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.config import load
from pipeline.config.policies import DIRECTORY, read
from pipeline.engines.names import build
from pipeline.sources.shared.schemas import SCHEMAS

Row = dict[str, Any]


def table(path: Path, rows: list[Row], schema: pa.Schema | None = None) -> Row:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    return {"path": str(path), "kind": path.parent.name, "rows": len(rows)}


def alias(identity: str, entity: str, name: str, **more: Any) -> Row:
    row: Row = {
        "source": "geonames",
        "source_id": identity,
        "entity_source_id": entity,
        "name": name,
        "language": None,
        "name_kind": "alternate",
        "is_preferred": False,
        "is_short": False,
        "is_colloquial": False,
        "is_historic": False,
        "valid_from": None,
        "valid_to": None,
        "source_release": "test",
        "license": "CC-BY-4.0",
        "provenance": "{}",
    }
    return row | more


def feature(identity: str, name: str, ascii_name: str) -> Row:
    return {
        "source": "geonames",
        "source_id": identity,
        "kind": "settlement",
        "name": name,
        "name_en": None,
        "latitude": 0.0,
        "longitude": 0.0,
        "feature_class": "P",
        "feature_code": "PPL",
        "subtype": "PPL",
        "country_code": "ZZ",
        "admin1_code": None,
        "admin2_code": None,
        "parent_source_id": None,
        "population": 1,
        "source_release": "test",
        "license": "CC-BY-4.0",
        "provenance": json.dumps({"asciiname": ascii_name, "attribution": "GeoNames"}),
    }


def inputs(root: Path) -> tuple[list[Row], dict[str, list[Row]]]:
    links = [
        (
            "city:a",
            "Lodz",
            None,
            '[{"source":"geonames","id":"1"},{"source":"overture","id":"ov-a"}]',
            "self",
        ),
        ("city:b", "Batavia", None, '[{"source":"geonames","id":"2"}]', "self"),
        ("city:c", "Frisco", "Frisco", '[{"source":"geonames","id":"3"}]', "self"),
    ]
    places = [{"place_id": c, "source_ids": ids} for c, _, _, ids, _ in links]
    places.append(
        {"place_id": "part", "source_ids": '[{"source":"geonames","id":"9"}]'}
    )
    cities = [
        {"city_id": c, "name": n, "name_en": e, "country_code": "ZZ"}
        for c, n, e, _, _ in links
    ]
    mapping = [{"place_id": c, "city_id": c, "method": m} for c, *_, m in links]
    mapping.append(
        {"place_id": "part", "city_id": "city:a", "method": "spatial_absorption"}
    )
    tables = [
        table(root / "places" / "ZZ.parquet", places),
        table(root / "canonical_cities" / "ZZ.parquet", cities),
        table(root / "place_to_city" / "ZZ.parquet", mapping),
    ]
    names = [
        alias("10", "1", "Łódź"),
        alias("11", "1", "Lodz"),  # the city's own name after folding
        alias("12", "1", "https://en.wikipedia.org/wiki/Łódź", language="link"),
        alias("13", "1", "91-001", language="post"),
        alias("14", "1", "Lodsch", language="de"),
        alias("15", "1", "Lodz City", language="en"),
        alias("16", "1", "Batavia", is_historic=True),  # names city:b
        alias("17", "1", "Litzmannstadt", valid_to="1945"),
        alias("18", "1", "Manchester of Poland", is_colloquial=True),
        alias("19", "1", "?!"),
        alias("20", "1", "L" * 65),
        alias("21", "9", "Absorbed Part"),
        alias("22", "1", "łódź", language="pl"),  # same folded key as 10
        alias("30", "3", "San Fran", is_colloquial=True),
    ]
    overture = [
        alias("ov-1", "ov-a", "Łódź Miasto", source="overture", license="ODbL-1.0"),
    ]
    sources = {
        "geonames": [
            table(root / "gn" / "names" / "part.parquet", names, SCHEMAS["names"]),
            table(
                root / "gn" / "places" / "part.parquet",
                [feature("1", "Łódź", "Lodz"), feature("2", "Batavia", "Batavia")],
                SCHEMAS["places"],
            ),
        ],
        "overture": [
            table(root / "ov" / "names" / "part.parquet", overture, SCHEMAS["names"])
        ],
    }
    return tables, sources


def run(root: Path, policy: Row | None = None) -> tuple[list[Row], Row]:
    config = load()
    tables, sources = inputs(root / "in")
    output = root / "out"
    build.build(
        root,
        output,
        tables,
        sources,
        policy or read(DIRECTORY / "names.yaml"),
        config.resources,
        config.engines.limits,
    )
    receipt = json.loads((output / "names.json").read_text())
    return pq.read_table(output / "names.parquet").to_pylist(), receipt


def test_names_link_filter_and_kind(tmp_path: Path) -> None:
    rows, receipt = run(tmp_path)
    kept = {(r["city_id"], r["name"], r["kind"]) for r in rows}
    assert kept == {
        ("city:a", "Łódź", "alternate"),
        ("city:a", "Lodsch", "alternate"),
        ("city:a", "Lodz City", "english"),
        ("city:a", "Litzmannstadt", "alternate"),
        ("city:a", "Łódź Miasto", "alternate"),
    }
    first = next(r for r in rows if r["name"] == "Łódź")
    assert first["source_id"] == "10" and first["place_id"] == "city:a"
    assert first["country_code"] == "ZZ" and first["license"] == "CC-BY-4.0"
    assert receipt["dropped"] == {
        "canonical": 4,
        "collision": 1,
        "colloquial": 2,
        "duplicate": 2,
        "empty": 1,
        "language": 2,
        "long": 1,
    }
    assert receipt["rows"] == 5 and receipt["max_per_city"] == 5
    assert "inputs_hash" not in json.dumps(receipt)


def test_names_are_sorted_and_stable(tmp_path: Path) -> None:
    first, _ = run(tmp_path / "one")
    second, _ = run(tmp_path / "two")
    assert first == second
    assert [(r["city_id"], r["name"]) for r in first] == sorted(
        (r["city_id"], r["name"]) for r in first
    )
    assert (tmp_path / "one/out/names.parquet").read_bytes() == (
        tmp_path / "two/out/names.parquet"
    ).read_bytes()


def test_ascii_name_from_a_linked_feature(tmp_path: Path) -> None:
    policy = read(DIRECTORY / "names.yaml")
    rows, _ = run(tmp_path, policy)
    assert ("city:b", "Batavia") not in {(r["city_id"], r["name"]) for r in rows}
    tables, sources = inputs(tmp_path / "ascii")
    places = pq.read_table(sources["geonames"][1]["path"]).to_pylist()
    places[1]["provenance"] = json.dumps({"asciiname": "Betawi"})
    pq.write_table(
        pa.Table.from_pylist(places, schema=SCHEMAS["places"]),
        sources["geonames"][1]["path"],
    )
    config = load()
    build.build(
        tmp_path,
        tmp_path / "ascii-out",
        tables,
        sources,
        policy,
        config.resources,
        config.engines.limits,
    )
    output = pq.read_table(tmp_path / "ascii-out/names.parquet").to_pylist()
    assert {(r["city_id"], r["name"], r["kind"]) for r in output} >= {
        ("city:b", "Betawi", "ascii")
    }


def test_policy_rejects_unknown_treatments(tmp_path: Path) -> None:
    policy = read(DIRECTORY / "names.yaml") | {"historic": "sometimes"}
    with pytest.raises(ValueError, match="historic"):
        run(tmp_path, policy)
