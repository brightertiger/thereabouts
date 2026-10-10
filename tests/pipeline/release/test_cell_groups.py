"""The client can route every retained block directly to one Parquet row group."""

from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from h3.api import basic_int as h3

from pipeline.files import file_record
from pipeline.release.assemble import assemble
from pipeline.release.source import Snapshot, external
from pipeline.release.verify import verify_dataset
from pipeline.runtime.jsonio import write_json

from .fixtures import fixture

Row = dict[str, Any]


def blocks_table(output: Path, manifest: Row) -> list[Row]:
    [entry] = [record for record in manifest["tables"] if record["kind"] == "blocks"]
    return pq.read_table(output / entry["path"]).to_pylist()


def split_blocks(snapshot: Snapshot) -> None:
    """Reverse file order and split each block across two input files."""
    tables = [
        entry for entry in snapshot.manifest["tables"] if entry["kind"] != "cells"
    ]
    for number, record in enumerate(snapshot.tables["cells"]):
        original = snapshot.path(record)
        table = pq.ParquetFile(original).read()
        row = table.to_pylist()[0]
        keys = sorted(h3.cell_to_children(int(record.block, 16), 8))[:3]
        rows = [{**row, "h3": f"{key:x}", "h3_uint64": key} for key in keys]
        for part, selected in enumerate((rows[:1], rows[1:])):
            path = snapshot.root / f"cells-reversed-{1 - number}-{part}.parquet"
            pq.write_table(pa.Table.from_pylist(selected, schema=table.schema), path)
            tables.append(
                {
                    **file_record(snapshot.root, path),
                    "kind": "cells",
                    "rows": len(selected),
                    "block": record.block,
                }
            )
    snapshot.manifest["tables"] = tables
    write_json(snapshot.root / "manifest.json", snapshot.manifest)


def test_blocks_span_input_files_and_batches_but_never_row_groups(
    tmp_path: Path,
) -> None:
    snapshot, config, guard = fixture(tmp_path)
    split_blocks(snapshot)
    snapshot = external(snapshot.root, config.h3)
    config.release.dataset.batch_rows = 1
    config.release.dataset.row_group_rows = 1
    output = tmp_path / "dataset"
    assemble(snapshot, output, config, guard, "identity")
    manifest = verify_dataset(output)
    cells = [record for record in manifest["tables"] if record["kind"] == "cells"]
    assert len(cells) == 1
    assert cells[0]["rows"] == 6
    assert cells[0]["blocks"] == [
        {"block": block, "row_group": index, "rows": 3}
        for index, block in enumerate(sorted(config.release.blocks))
    ]
    with pq.ParquetFile(output / cells[0]["path"]) as file:
        assert file.num_row_groups == 2
        column = file.schema_arrow.get_field_index("block")
        assert column == len(file.schema_arrow) - 1
        for entry in cells[0]["blocks"]:
            group = file.read_row_group(entry["row_group"])
            keys = group["h3_uint64"].to_pylist()
            assert len(keys) == len(set(keys)) == entry["rows"]
            assert {f"{h3.cell_to_parent(key, 3):x}" for key in keys} == {
                entry["block"]
            }
            assert group["block"].to_pylist() == [entry["block"]] * entry["rows"]
            # One block per row group: its statistics admit exactly that block.
            chunk = file.metadata.row_group(entry["row_group"]).column(column)
            assert chunk.statistics is not None
            assert chunk.statistics.min == chunk.statistics.max == entry["block"]
    assert [row["reference_cells"] for row in blocks_table(output, manifest)] == [3, 3]


def test_empty_blocks_keep_coverage_without_a_row_group(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    config.release.countries = ["SG"]
    output = tmp_path / "dataset"
    assemble(snapshot, output, config, guard, "identity")
    manifest = verify_dataset(output)
    cells = [record for record in manifest["tables"] if record["kind"] == "cells"]
    assert cells and all(
        record["blocks"] == [] and record["rows"] == 0 for record in cells
    )
    # Covered blocks without selected rows answer no_land, as legacy files did.
    covered = [block for record in cells for block in record["empty_blocks"]]
    assert covered == sorted(config.release.blocks, key=lambda b: int(b, 16))
    assert all(
        pq.read_metadata(output / entry["path"]).num_row_groups == 0 for entry in cells
    )
    assert blocks_table(output, manifest) == [
        {
            "block": block,
            "cell_group": f"{h3.cell_to_parent(int(block, 16), 1):x}",
            "path": record["path"],
            "row_group": None,
            "row_count": 0,
            "reference_cells": 0,
        }
        for record in cells
        for block in record["empty_blocks"]
    ]


def test_the_blocks_table_indexes_every_stored_block(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    output = tmp_path / "dataset"
    assemble(snapshot, output, config, guard, "identity")
    manifest = verify_dataset(output)
    [cells] = [record for record in manifest["tables"] if record["kind"] == "cells"]
    group = PurePosixPath(cells["path"]).parent.name.removeprefix("group=")
    assert blocks_table(output, manifest) == [
        {
            "block": entry["block"],
            "cell_group": group,
            "path": cells["path"],
            "row_group": entry["row_group"],
            "row_count": entry["rows"],
            "reference_cells": 1,
        }
        for entry in cells["blocks"]
    ]


def test_a_repeated_cell_key_is_refused(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    record = snapshot.tables["cells"][0]
    path = snapshot.root / "cells-repeated.parquet"
    pq.write_table(pq.read_table(snapshot.path(record)), path)
    snapshot.manifest["tables"].append(
        {
            **file_record(snapshot.root, path),
            "kind": "cells",
            "rows": record.rows,
            "block": record.block,
        }
    )
    write_json(snapshot.root / "manifest.json", snapshot.manifest)
    snapshot = external(snapshot.root, config.h3)
    output = tmp_path / "dataset"
    with pytest.raises(ValueError, match="Repeated cell key"):
        assemble(snapshot, output, config, guard, "identity")
    assert not output.exists()


def test_a_blocks_table_that_disagrees_with_the_index_refuses(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    output = tmp_path / "dataset"
    assemble(snapshot, output, config, guard, "identity")
    manifest = verify_dataset(output)
    [entry] = [record for record in manifest["tables"] if record["kind"] == "blocks"]
    path = output / entry["path"]
    table = pq.read_table(path)
    rows = table.to_pylist()
    rows[0]["reference_cells"] += 1
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    for record in [*manifest["tables"], *manifest["files"]]:
        if record["path"] == entry["path"]:
            record.update(file_record(output, path))
    write_json(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="blocks table"):
        verify_dataset(output)


def test_mislabelled_input_block_is_rejected(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    cells = [
        record for record in snapshot.manifest["tables"] if record["kind"] == "cells"
    ]
    cells[0]["block"], cells[1]["block"] = cells[1]["block"], cells[0]["block"]
    write_json(snapshot.root / "manifest.json", snapshot.manifest)
    snapshot = external(snapshot.root, config.h3)
    output = tmp_path / "dataset"
    with pytest.raises(ValueError, match="do not belong to declared block"):
        assemble(snapshot, output, config, guard, "identity")
    assert not output.exists()


@pytest.mark.parametrize(
    "fault",
    ["missing", "rows", "position", "order", "block", "empty_overlap", "empty_parent"],
)
def test_invalid_manifest_block_index_refuses(tmp_path: Path, fault: str) -> None:
    snapshot, config, guard = fixture(tmp_path)
    output = tmp_path / "dataset"
    assemble(snapshot, output, config, guard, "identity")
    manifest = verify_dataset(output)
    for record in [*manifest["tables"], *manifest["files"]]:
        if record.get("kind") != "cells":
            continue
        if fault == "missing":
            del record["blocks"]
        elif fault == "rows":
            record["blocks"][0]["rows"] += 1
        elif fault == "position":
            record["blocks"][0]["row_group"] = 1
        elif fault == "order":
            record["blocks"].reverse()
        elif fault == "empty_overlap":
            record["empty_blocks"] = [record["blocks"][0]["block"]]
        elif fault == "empty_parent":
            record["empty_blocks"] = [f"{h3.latlng_to_cell(0, 0, 3):x}"]
        else:
            record["blocks"][0]["block"] = config.release.blocks[1]
    write_json(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Cell"):
        verify_dataset(output)
