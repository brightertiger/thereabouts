"""Golden content neutrality uses logical rows, types and duplicate counts."""

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from build_data.acquire.artifacts import read_json
from build_data.acquire.io import write_json
from build_data.digest_golden import digest_dataset, main
from build_data.golden import paths
from build_data.reconcile.common import Row


def dataset(root: Path, parts: list[pa.Table], *, portable: bool = False) -> Path:
    output = root / "golden"
    output.mkdir(parents=True)
    records = []
    for i, table in enumerate(parts):
        path = output / f"{len(parts) - i}.parquet"
        pq.write_table(
            table,
            path,
            compression="zstd" if portable else "snappy",
            row_group_size=1 if portable else 10,
        )
        records.append({"kind": "cells", "path": str(path), "rows": table.num_rows})
    value: Row = {"completed": True, "tables": list(reversed(records))}
    if portable:
        value["data_root"] = ".."
        paths.write(output / "manifest.json", value, root)
    else:
        write_json(output / "manifest.json", value)
    return output


def test_metadata_order_partitions_and_root_do_not_change_content(
    tmp_path: Path,
) -> None:
    table = pa.table(
        {
            "id": [2, 1, 1],
            "value": ["x", None, None],
            "bytes": [b"\x00", b"", None],
            "list": [["a", "b"], [], None],
        }
    )
    first = dataset(tmp_path / "first", [table])
    changed_metadata = table.replace_schema_metadata(
        {b"created_at": b"a different time"}
    )
    second = dataset(
        tmp_path / "second",
        [
            changed_metadata.take([2, 0]).select(list(reversed(table.column_names))),
            changed_metadata.take([1]).select(list(reversed(table.column_names))),
        ],
        portable=True,
    )
    before = digest_dataset(first, temp_dir=tmp_path)
    assert digest_dataset(second, temp_dir=tmp_path) == before
    relocated = tmp_path / "relocated"
    second.parent.rename(relocated)
    assert digest_dataset(relocated / "golden", temp_dir=tmp_path) == before
    assert before["tables"]["cells"]["rows"] == 3


@pytest.mark.parametrize("change", ["value", "duplicate", "type", "null", "kind"])
def test_real_differences_change_digest(tmp_path: Path, change: str) -> None:
    values = [1, 2, 2]
    before = dataset(tmp_path / "a", [pa.table({"value": values})])
    if change == "value":
        values = [1, 2, 3]
    elif change == "duplicate":
        values = [1, 1, 2]
    array = pa.array(values, type=pa.int32() if change == "type" else pa.int64())
    if change == "null":
        array = pa.array([1, 2, None], type=pa.int64())
    after = dataset(tmp_path / "b", [pa.table({"value": array})])
    if change == "kind":
        saved = read_json(after / "manifest.json")
        saved["tables"][0]["kind"] = "places"
        write_json(after / "manifest.json", saved)
    assert digest_dataset(before, temp_dir=tmp_path) != digest_dataset(
        after, temp_dir=tmp_path
    )


def test_empty_tables_and_nonfinite_values_are_deterministic(tmp_path: Path) -> None:
    schema = pa.schema([("f", pa.float64())])
    empty = pa.Table.from_pylist([], schema=schema)
    value = dataset(tmp_path / "empty", [empty])
    assert digest_dataset(value, temp_dir=tmp_path)["tables"]["cells"]["rows"] == 0
    table = pa.table({"f": [float("nan"), float("inf"), float("-inf"), 0.0, -0.0]})
    a = dataset(tmp_path / "a", [table])
    b = dataset(tmp_path / "b", [table.take([4, 2, 3, 0, 1])])
    assert digest_dataset(a, temp_dir=tmp_path) == digest_dataset(b, temp_dir=tmp_path)


def test_incomplete_duplicate_and_inconsistent_manifests_fail(tmp_path: Path) -> None:
    output = dataset(tmp_path, [pa.table({"id": [1]})])
    saved = read_json(output / "manifest.json")
    write_json(output / "manifest.json", {**saved, "completed": False})
    with pytest.raises(ValueError, match="completed"):
        digest_dataset(output, temp_dir=tmp_path)
    write_json(output / "manifest.json", {**saved, "tables": saved["tables"] * 2})
    with pytest.raises(ValueError, match="Duplicate"):
        digest_dataset(output, temp_dir=tmp_path)
    saved["tables"][0]["rows"] += 1
    write_json(output / "manifest.json", saved)
    with pytest.raises(ValueError, match="row count"):
        digest_dataset(output, temp_dir=tmp_path)
    other = dataset(
        tmp_path / "other", [pa.table({"id": [1]}), pa.table({"value": [1]})]
    )
    with pytest.raises(ValueError, match="schemas"):
        digest_dataset(other, temp_dir=tmp_path)


def test_cli_writes_comparable_json_and_returns_failure_for_differences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = dataset(tmp_path / "a", [pa.table({"id": [1]})])
    b = dataset(tmp_path / "b", [pa.table({"id": [2]})])
    baseline = tmp_path / "before.json"
    output = tmp_path / "after.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "digest_golden",
            str(a),
            "--output",
            str(baseline),
            "--temp-dir",
            str(tmp_path),
        ],
    )
    main()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "digest_golden",
            str(a),
            "--output",
            str(output),
            "--compare",
            str(baseline),
            "--temp-dir",
            str(tmp_path),
        ],
    )
    main()
    assert baseline.read_bytes() == output.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "digest_golden",
            str(b),
            "--output",
            str(output),
            "--compare",
            str(baseline),
            "--temp-dir",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit, match="contents differ"):
        main()
    assert read_json(output) != read_json(baseline)
