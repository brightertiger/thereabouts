from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from h3.api import basic_int as h3

from build_data.serve.checkpoints import file_record
from build_data.serve.export import export
from build_data.serve.metadata import write_manifest
from thereabouts.packs.address import address
from thereabouts.packs.jsonio import parse
from thereabouts.packs.spatial import Spatial
from thereabouts.packs.verify import verify

from .fixtures import cell, place


@pytest.mark.parametrize("repeat,width", [(1, 0), (2, 2)])
def test_many_unique_labels(
    snapshot: tuple[Path, Path], tmp_path: Path, repeat: int, width: int
) -> None:
    value = parse(snapshot[0].read_bytes())
    root = snapshot[1].parent
    places = next(r for r in value["tables"] if r["kind"] == "places")
    path = root / places["path"]
    table = pq.ParquetFile(path).read()
    additions = [
        place(f"settlement:synthetic:{i:03d}", "settlement", "country:AA")
        for i in range(300)
    ]
    updated = pa.Table.from_pylist(
        [*table.to_pylist(), *additions], schema=table.schema
    )
    pq.write_table(updated, path)
    places.update(file_record(path, root), rows=updated.num_rows)
    record = next(r for r in value["tables"] if r["kind"] == "cells" and r["rows"] > 1)
    path = root / record["path"]
    table = pq.ParquetFile(path).read()
    fine = h3.cell_to_children(int(record["block"], 16), 8)
    data = [
        {**cell(key, "rural_nearest"), "city_id": additions[i % 300]["place_id"]}
        for i, key in enumerate(fine[: 300 * repeat])
    ]
    pq.write_table(pa.Table.from_pylist(data, schema=table.schema), path)
    record.update(file_record(path, root), rows=len(data))
    write_manifest(snapshot[0], value)
    pack = export(*snapshot, tmp_path / "pack")
    manifest = verify(pack)
    shard = next(r for r in manifest["files"] if r["kind"] == "cells")
    spatial = Spatial(pack / shard["path"], manifest["place_count"])
    try:
        block = address(int(record["block"], 16), 3)[0]
        assert spatial.blocks[block].width == width
        if repeat == 2:
            first = spatial.lookup(*address(fine[0], 8))
            repeated = spatial.lookup(*address(fine[300], 8))
            assert first is not None and repeated is not None
            assert first[1] == repeated[1]
        assert spatial.lookup(*address(fine[300 * repeat], 8)) is None
    finally:
        spatial.close()


def test_empty_catalogue_still_preserves_unassigned_land(
    snapshot: tuple[Path, Path], tmp_path: Path
) -> None:
    value = parse(snapshot[0].read_bytes())
    root = snapshot[1].parent
    for record in value["tables"]:
        if record["kind"] != "cells":
            continue
        path = root / record["path"]
        table = pq.ParquetFile(path).read()
        data = [
            cell(row["h3_uint64"], None, unassigned=True) for row in table.to_pylist()
        ]
        pq.write_table(pa.Table.from_pylist(data, schema=table.schema), path)
        record.update(file_record(path, root))
    write_manifest(snapshot[0], value)
    pack = export(*snapshot, tmp_path / "pack")
    manifest = verify(pack)
    assert manifest["place_count"] == 0
    assert not any(r["kind"] == "catalogue" for r in manifest["files"])
    record = next(r for r in manifest["files"] if r["kind"] == "cells")
    spatial = Spatial(pack / record["path"], 0)
    try:
        block = next(b for b in spatial.blocks.values() if b.count)
        assert spatial.label(block, 0) == (0, 0, 0, 0)
    finally:
        spatial.close()
