from __future__ import annotations

from pathlib import Path

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import file_record
from build_data.golden import joins
from build_data.golden.cells import digest
from build_data.golden.inputs import Inputs
from build_data.golden.metrics import measure
from build_data.golden.reader import Cells
from build_data.golden.run import build_blocks, committed
from build_data.golden.schemas import CELLS
from build_data.reconcile.common import Row


def table(root: Path, cell: str, rows: list[Row]) -> Row:
    path = root / f"{cell}.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=CELLS), path)
    return {**file_record(path), "kind": "cells", "block": cell, "rows": len(rows)}


def test_partial_lookup_join_preserves_country_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(tmp_path)
    workspace.work.mkdir()
    cell = h3.latlng_to_cell(10, 10, 8)
    root = h3.cell_to_parent(cell, 3)
    ocean = h3.latlng_to_cell(0, -140, 8)
    pending = h3.latlng_to_cell(40, 40, 8)
    cells = [
        table(
            tmp_path,
            root,
            [
                {
                    "h3": root,
                    "h3_uint64": h3.str_to_int(root),
                    "h3_resolution": 3,
                    "country_id": "country:ZZ",
                    "state_id": "state:Z",
                    "city_id": "city:Z",
                    "city_method": "area",
                    "land_method": "land",
                }
            ],
        ),
        table(tmp_path, h3.cell_to_parent(ocean, 3), []),
    ]
    source = tmp_path / "source.parquet"
    pq.write_table(
        pa.table(
            {
                "country_code": ["YY", "ZZ", "ZZ", "ZZ", "ZZ"],
                "h3": [cell, cell, ocean, pending, None],
                "h3_uint64": pa.array(
                    [
                        h3.str_to_int(c) if c else None
                        for c in [cell, cell, ocean, pending, None]
                    ],
                    type=pa.uint64(),
                ),
            }
        ),
        source,
    )
    part = {**file_record(source), "kind": "postal_codes", "rows": 5}
    monkeypatch.setattr(
        joins,
        "load_manifest",
        lambda w, s: {"partitions": [part]} if s == "postal" else {"partitions": []},
    )
    monkeypatch.setattr(joins, "budget", lambda w, required=0: None)
    exported = joins.export(workspace, cells)
    rows = pq.read_table(exported[0]["path"]).to_pylist()
    assert sorted(r["cell_status"] for r in rows) == [
        "ineligible",
        "matched",
        "matched",
        "pending",
        "unlocated",
    ]
    assert exported[0]["counts"]["disagreements"] == 1
    assert exported[0]["counts"]["compared"] == 2
    assert any(
        r["country_code"] == "YY"
        and r["cell_country_code"] == "ZZ"
        and r["country_disagrees"]
        for r in rows
    )
    destination = Path(exported[0]["path"])
    before = destination.stat().st_mtime_ns
    assert joins.export(workspace, cells) == exported
    assert destination.stat().st_mtime_ns == before
    # New ready (empty ocean) block fills the pending row on the same command.
    cells.append(table(tmp_path, h3.cell_to_parent(pending, 3), []))
    refreshed = joins.export(workspace, cells)
    assert refreshed[0]["counts"].get("pending", 0) == 0
    assert refreshed[0]["counts"]["ineligible"] == 2
    reader = Cells(cells)
    assert reader.lookup(cell)["city_id"] == "city:Z"
    assert reader.lookup(ocean)["cell_status"] == "ineligible"
    with pytest.raises(ValueError, match="resolution-8"):
        reader.lookup(root)
    places_path = tmp_path / "places.parquet"
    pq.write_table(
        pa.table(
            {
                "place_id": ["country:ZZ", "state:Z", "city:Z"],
                "parent_id": [None, "country:ZZ", "state:Z"],
                "sovereign_id": ["country:ZZ"] * 3,
            }
        ),
        places_path,
    )
    metrics = measure(workspace, [{"path": str(places_path), "kind": "places"}], cells)
    assert metrics["represented_r8_centres"]["eligible"] == 7**5
    assert metrics["represented_r8_centres"]["city"] == 7**5
    assert metrics["missing_cell_place_ids"] == 0
    assert metrics["duplicate_place_ids"] == 0


def test_block_waits_for_every_dependency_and_stale_or_corrupt_output_is_not_reused(
    tmp_path: Path,
) -> None:
    workspace = Workspace(tmp_path)
    inputs = Inputs({"ZZ": {"sha256": "one"}}, {"sha256": "land"}, {}, {}, "test")
    root = h3.latlng_to_cell(0, 0, 3)
    plan = [{"root": root, "countries": ["YY", "ZZ"]}]
    built, status = build_blocks(workspace, inputs, plan)
    assert not built
    assert status["waiting_blocks"] == 1
    assert status["remaining_blocks"] == 1
    assert status["waiting_countries"] == ["YY"]
    inputs.countries["YY"] = {"sha256": "two"}
    output = tmp_path / "block.bin"
    output.write_bytes(b"verified")
    expected = digest(inputs, ["YY", "ZZ"], "builder")
    Ledger(workspace.ledger_path).complete(
        "golden.cells", root, expected, [output], metadata={"countries": ["YY", "ZZ"]}
    )
    assert root in committed(workspace, inputs, plan, "builder")
    assert not committed(workspace, inputs, plan, "new builder")
    output.write_bytes(b"corrupt!")
    assert not committed(workspace, inputs, plan, "builder")
