"""Cross-source contracts and bounded atomic Parquet publication."""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely.geometry import Point, box

from build_data.acquire import schemas
from build_data.acquire.parquet import validate_parquet, write_partition
from build_data.acquire.schemas import SCHEMAS, Kind, validate_table


def example(kind: Kind, **updates: object) -> pa.Table:
    row: dict[str, object] = {
        "source": "overture",
        "source_id": "area-1",
        "source_release": "release",
        "license": "ODbL-1.0",
        "provenance": json.dumps(
            {
                "source_url": "https://example.test/input",
                "license_url": "https://example.test/license",
                "attribution": "Example contributors",
            }
        ),
    }
    if kind == "areas":
        row.update(
            entity_id="division-1",
            kind="country",
            geometry=box(1, 2, 3, 4).wkb,
            xmin=1,
            ymin=2,
            xmax=3,
            ymax=4,
        )
    elif kind == "places":
        row.update(
            kind="settlement",
            name="Monaco",
            latitude=43.7,
            longitude=7.4,
            country_code="MC",
            population=0,
        )
    else:
        row.update(
            entity_source_id="division-1",
            name="Monaco",
            language="en",
            is_preferred=True,
            is_short=False,
            is_colloquial=False,
            is_historic=False,
        )
    row.update(updates)
    return pa.Table.from_pylist([row], schema=SCHEMAS[kind])


@pytest.mark.parametrize("kind", ["areas", "places", "names"])
def test_schema_roundtrip_and_partition(kind: Kind, tmp_path: Path) -> None:
    table = example(kind)
    validate_table(table, kind)
    destination = tmp_path / "part.parquet"
    write_partition(destination, kind, [table, *table.to_batches()])
    validate_parquet(destination, kind)
    assert pq.read_table(destination).equals(pa.concat_tables([table, table]))


@pytest.mark.parametrize("kind", ["areas", "places", "names"])
def test_rejects_wrong_schema_null_and_missing_provenance(kind: Kind) -> None:
    table = example(kind)
    with pytest.raises(ValueError, match="schema"):
        validate_table(table.drop(["source_id"]), kind)
    with pytest.raises(ValueError, match="null"):
        validate_table(example(kind, source_id=None), kind)
    with pytest.raises(ValueError, match="provenance"):
        validate_table(example(kind, provenance="{}"), kind)


@pytest.mark.parametrize(
    "updates",
    [
        {"latitude": float("nan")},
        {"longitude": float("inf")},
        {"latitude": 91},
        {"population": -1},
        {"country_code": "GBR"},
        {"name": ""},
        {"source": "unknown"},
    ],
)
def test_invalid_point_values(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_table(example("places", **updates), "places")


@pytest.mark.parametrize(
    "updates",
    [
        {"geometry": b"not wkb"},
        {"geometry": Point(1, 2).wkb},
        {"xmin": 0},
        {"xmax": 181},
        {"xmin": float("nan")},
        {"geometry": box(1, 2, 3, 4).buffer(-100).wkb},
    ],
)
def test_invalid_geometry_or_bbox(updates: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        validate_table(example("areas", **updates), "areas")


def test_batch_and_row_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    table = example("places")
    monkeypatch.setattr(schemas, "MAX_BATCH_BYTES", table.nbytes - 1)
    with pytest.raises(ValueError, match="Batch"):
        validate_table(table, "places")
    monkeypatch.setattr(schemas, "MAX_BATCH_BYTES", table.nbytes + 1)
    monkeypatch.setattr(schemas, "MAX_ROW_BYTES", table.nbytes - 1)
    with pytest.raises(ValueError, match="Row"):
        validate_table(table, "places")


def test_failed_parquet_write_preserves_previous_partition(tmp_path: Path) -> None:
    destination = tmp_path / "part.parquet"
    valid = example("places")
    write_partition(destination, "places", [valid])
    original = destination.read_bytes()
    with pytest.raises(ValueError):
        write_partition(destination, "places", [valid, example("places", latitude=100)])
    assert destination.read_bytes() == original
    assert not list(tmp_path.glob("*.part"))


def test_partition_cap_checked_on_write_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from build_data.acquire import parquet

    destination = tmp_path / "part.parquet"
    table = example("places")
    write_partition(destination, "places", [table])
    monkeypatch.setattr(parquet, "MAX_PARTITION_BYTES", table.nbytes - 1)
    with pytest.raises(ValueError, match="Partition"):
        write_partition(tmp_path / "too-large.parquet", "places", [table])
    with pytest.raises(ValueError, match="128 MB"):
        validate_parquet(destination, "places")


def test_dictionary_expansion_is_rejected_before_decode(tmp_path: Path) -> None:
    destination = tmp_path / "dictionary.parquet"
    pq.write_table(example("places"), destination, use_dictionary=True)
    with pytest.raises(ValueError, match="dictionary"):
        validate_parquet(destination, "places")
