"""Failures in source semantics must never publish a serving directory."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from build_data.serve.checkpoints import file_record
from build_data.serve.export import export
from build_data.serve.metadata import write_manifest
from thereabouts.packs.errors import CorruptPackError
from thereabouts.packs.jsonio import parse


@pytest.mark.parametrize(
    "case",
    ["method", "dangling", "overlap", "duplicate", "wrong_block", "schema", "pending"],
)
def test_reject_bad_golden_rows(
    snapshot: tuple[Path, Path], tmp_path: Path, case: str
) -> None:
    value = parse(snapshot[0].read_bytes())
    root = snapshot[1].parent
    record = next(r for r in value["tables"] if r["kind"] == "cells" and r["rows"] > 1)
    path = root / record["path"]
    table = pq.ParquetFile(path).read()
    rows = table.to_pylist()
    if case == "method":
        rows[0]["city_method"] = "nearest"
    elif case == "dangling":
        rows[0]["city_id"] = "city:missing"
    elif case == "duplicate":
        rows.append(rows[0])
    elif case == "wrong_block":
        record["block"] = next(
            r["block"]
            for r in value["tables"]
            if r["kind"] == "cells" and r["rows"] == 0
        )
        value["tables"] = [
            r for r in value["tables"] if r["kind"] != "cells" or r["rows"]
        ]
    elif case == "overlap":
        from h3.api import basic_int as h3

        parent = h3.cell_to_parent(rows[0]["h3_uint64"], 4)
        rows.append(
            {
                **rows[0],
                "h3": h3.int_to_str(parent),
                "h3_uint64": parent,
                "h3_resolution": 4,
            }
        )
    elif case == "pending":
        lookup = root / "golden/postal.parquet"
        pq.write_table(pa.table({"cell_status": ["pending"]}), lookup)
        value["tables"].append(file_record(lookup, root, rows=1, kind="postal_codes"))
    table = pa.Table.from_pylist(rows, schema=table.schema)
    if case == "schema":
        table = table.drop(["city_method"])
    pq.write_table(table, path)
    record.update(file_record(path, root), rows=table.num_rows)
    write_manifest(snapshot[0], value)
    with pytest.raises((ValueError, CorruptPackError)):
        export(*snapshot, tmp_path / "pack", shard_bytes=1024)
    assert not (tmp_path / "pack").exists()
