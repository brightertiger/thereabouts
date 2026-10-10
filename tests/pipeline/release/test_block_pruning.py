"""Generic engines read one cells row group for a point, by the block column alone.

H3 integers order by resolution before location, so a row group holding several
resolutions spans most of the key range and key statistics admit every block.
The block column is constant within a row group, so `block = ?` admits exactly one.
"""

import shutil
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import pytest
from h3.api import basic_int as h3

from pipeline.files import file_record
from pipeline.release.assemble import assemble
from pipeline.release.source import Snapshot, external
from pipeline.release.verify import verify_dataset
from pipeline.runtime.jsonio import write_json

from .fixtures import fixture

# The README's DuckDB lookup: the block first, then the point's stored ancestors.
LOOKUP = """SELECT h3_resolution FROM read_parquet(?)
  WHERE {block}h3_uint64 IN (SELECT unnest(?::UBIGINT[]))"""


def mixed_blocks(snapshot: Snapshot) -> dict[str, int]:
    """Store a resolution-5 row and an unrelated resolution-8 row in each block.

    Returns each block's resolution-8 point.
    """
    tables = [
        entry for entry in snapshot.manifest["tables"] if entry["kind"] != "cells"
    ]
    points = {}
    for number, record in enumerate(snapshot.tables["cells"]):
        table = pq.read_table(snapshot.path(record))
        row = table.to_pylist()[0]
        coarse, other = sorted(h3.cell_to_children(int(record.block, 16), 5))[:2]
        points[record.block] = h3.cell_to_center_child(other, 8)
        rows = [
            {**row, "h3": f"{key:x}", "h3_uint64": key, "h3_resolution": resolution}
            for key, resolution in ((coarse, 5), (points[record.block], 8))
        ]
        path = snapshot.root / f"cells-mixed-{number}.parquet"
        pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
        tables.append(
            {
                **file_record(snapshot.root, path),
                "kind": "cells",
                "rows": len(rows),
                "block": record.block,
            }
        )
    snapshot.manifest["tables"] = tables
    write_json(snapshot.root / "manifest.json", snapshot.manifest)
    return points


def blank_other_row_groups(path: Path, keep: int) -> None:
    """Zero every page outside one row group, so reading any of them fails."""
    metadata = pq.read_metadata(path)
    with path.open("r+b") as stream:
        for number in range(metadata.num_row_groups):
            if number == keep:
                continue
            group = metadata.row_group(number)
            for index in range(group.num_columns):
                chunk = group.column(index)
                start = (
                    chunk.dictionary_page_offset
                    if chunk.has_dictionary_page
                    else chunk.data_page_offset
                )
                assert start is not None
                stream.seek(start)
                stream.write(bytes(chunk.total_compressed_size))


def test_a_point_lookup_reads_only_its_block_row_group(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    points = mixed_blocks(snapshot)
    snapshot = external(snapshot.root, config.h3)
    output = tmp_path / "dataset"
    assemble(snapshot, output, config, guard, "identity")
    manifest = verify_dataset(output)
    [cells] = [record for record in manifest["tables"] if record["kind"] == "cells"]
    [index] = [record for record in manifest["tables"] if record["kind"] == "blocks"]
    reference = pq.read_table(output / index["path"])["reference_cells"]
    assert reference.to_pylist() == [7**3 + 1] * 2
    target = cells["blocks"][1]
    point = points[target["block"]]
    keys = [h3.cell_to_parent(point, level) for level in range(3, 9)]
    path = tmp_path / "copy.parquet"
    shutil.copyfile(output / cells["path"], path)
    with pq.ParquetFile(path) as file:
        assert file.num_row_groups == len(cells["blocks"]) == 2
        key = file.schema_arrow.get_field_index("h3_uint64")
        block = file.schema_arrow.get_field_index("block")
        for entry in cells["blocks"]:
            group = file.metadata.row_group(entry["row_group"])
            keyed = group.column(key).statistics
            blocked = group.column(block).statistics
            assert keyed is not None and blocked is not None
            # Key statistics admit the lookup in every row group, not only its own.
            assert any(keyed.min <= value <= keyed.max for value in keys)
            assert blocked.min == blocked.max == entry["block"]
    blank_other_row_groups(path, target["row_group"])

    connection = duckdb.connect()
    found = connection.execute(
        LOOKUP.format(block="block = ? AND "), [str(path), target["block"], keys]
    ).fetchall()
    assert found == [(8,)]
    with pytest.raises(duckdb.Error):
        connection.execute(LOOKUP.format(block=""), [str(path), keys]).fetchall()
    connection.close()

    dataset = ds.dataset(path, format="parquet")
    wanted = ds.field("h3_uint64").isin(pa.array(keys, pa.uint64()))
    table = dataset.to_table(
        filter=(ds.field("block") == target["block"]) & wanted,
        columns=["h3_resolution"],
    )
    assert table["h3_resolution"].to_pylist() == [8]
    with pytest.raises((OSError, pa.ArrowException)):
        dataset.to_table(filter=wanted, columns=["h3_resolution"])
