"""Grouped Parquet routes must preserve the legacy block pack byte for byte."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from tests.tools.synthetic_dataset import golden
from thereabouts import Geocoder, WriterInputError, _core
from thereabouts.store_files import sha256

FIXTURES = Path(__file__).parents[2] / "fixtures"


def setup(
    root: Path, *, keep_empty: bool = False
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    manifest_path, _ = golden(root)
    manifest = json.loads(manifest_path.read_text())
    if not keep_empty:
        manifest["tables"] = [
            t for t in manifest["tables"] if t["kind"] != "cells" or t["rows"] > 0
        ]
    cells = [t for t in manifest["tables"] if t["kind"] == "cells" and t["rows"]]
    parent = h3.cell_to_parent(cells[0]["block"], 1)
    used = {t["block"] for t in cells}
    block = next(b for b in h3.cell_to_children(parent, 3) if b not in used)
    original = pq.ParquetFile(root / cells[0]["path"]).read()
    row = original.to_pylist()[0] | {
        "h3": block,
        "h3_uint64": h3.str_to_int(block),
        "h3_resolution": 3,
    }
    path = root / "golden/cells" / f"{block}.parquet"
    pq.write_table(pa.Table.from_pylist([row], schema=original.schema), path)
    manifest["tables"].append(
        dict(
            kind="cells",
            block=block,
            path=path.relative_to(root).as_posix(),
            rows=1,
            size=path.stat().st_size,
            sha256=sha256(path),
        )
    )
    manifest_path.write_text(json.dumps(manifest))
    options = json.loads((FIXTURES / "packs/core-synthetic/manifest.json").read_text())[
        "inputs"
    ]["options"]
    return manifest_path, manifest, options


def coalesce(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for table in manifest["tables"]:
        if table["kind"] == "cells":
            groups[h3.cell_to_parent(table["block"], 1)].append(table)
    grouped = []
    for parent, entries in sorted(groups.items()):
        entries.sort(key=lambda t: t["block"])
        # Zero-row legacy files become covered empty blocks without row groups.
        tables = [t for t in entries if t["rows"]]
        path = root / f"golden/cells/group={parent}/part.parquet"
        path.parent.mkdir(parents=True)
        schema = pq.ParquetFile(root / entries[0]["path"]).schema_arrow
        with pq.ParquetWriter(path, schema) as writer:
            for table in tables:
                writer.write_table(pq.ParquetFile(root / table["path"]).read())
        assert pq.ParquetFile(path).num_row_groups == len(tables)
        record = dict(
            kind="cells",
            path=path.relative_to(root).as_posix(),
            rows=sum(t["rows"] for t in tables),
            size=path.stat().st_size,
            sha256=sha256(path),
            blocks=[
                dict(block=t["block"], row_group=i, rows=t["rows"])
                for i, t in enumerate(tables)
            ],
        )
        if len(tables) < len(entries):
            record["empty_blocks"] = [t["block"] for t in entries if not t["rows"]]
        grouped.append(record)
    manifest["tables"] = [
        t for t in manifest["tables"] if t["kind"] != "cells"
    ] + grouped
    return grouped


def test_grouped_and_legacy_layouts_emit_identical_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    path, manifest, options = setup(root)
    legacy = tmp_path / "legacy"
    before = _core.write_pack(str(path.parent), "core", str(legacy), options)
    grouped = coalesce(root, manifest)
    assert max(len(t["blocks"]) for t in grouped) > 1
    assert all(b["rows"] > 0 for t in grouped for b in t["blocks"])
    path.write_text(json.dumps(manifest))
    destination = tmp_path / "grouped"
    after = _core.write_pack(str(path.parent), "core", str(destination), options)
    assert before["files"] == after["files"]
    assert before["input_digest"] != after["input_digest"]
    with Geocoder(legacy) as old, Geocoder(destination) as new:
        for table in grouped:
            for block in table["blocks"]:
                assert old.from_h3(block["block"], evidence=True) == new.from_h3(
                    block["block"], evidence=True
                )
    assert _core.verify_pack(str(destination))["family"] == "core"


def test_covered_empty_blocks_match_legacy_zero_row_files(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    path, manifest, options = setup(root, keep_empty=True)
    empty = next(t["block"] for t in manifest["tables"] if t.get("rows") == 0)
    legacy = tmp_path / "legacy"
    before = _core.write_pack(str(path.parent), "core", str(legacy), options)
    grouped = coalesce(root, manifest)
    assert [b for t in grouped for b in t.get("empty_blocks", [])] == [empty]
    path.write_text(json.dumps(manifest))
    destination = tmp_path / "grouped"
    after = _core.write_pack(str(path.parent), "core", str(destination), options)
    assert before["files"] == after["files"]
    ocean = h3.cell_to_center_child(empty, 8)
    with Geocoder(legacy) as old, Geocoder(destination) as new:
        result = new.from_h3(ocean, evidence=True)
        assert result == old.from_h3(ocean, evidence=True)
        assert result.status == "not_found"
        assert result.evidence is not None and result.evidence.reason == "no_land"


@pytest.mark.parametrize(
    "fault",
    [
        "empty_overlap",
        "empty_order",
        "empty_parent",
        "empty_legacy",
        "order",
        "rows",
        "parent",
        "duplicate",
        "mixed",
        "missing_group",
        "zero_rows",
        "path_parent",
        "no_parent",
    ],
)
def test_grouped_manifest_routing_is_validated(tmp_path: Path, fault: str) -> None:
    root = tmp_path / "dataset"
    path, manifest, options = setup(root)
    tables = coalesce(root, manifest)
    table = next(t for t in tables if len(t["blocks"]) > 1)
    used = {b["block"] for t in tables for b in t["blocks"]}
    spare = sorted(
        b
        for b in h3.cell_to_children(
            h3.cell_to_parent(table["blocks"][0]["block"], 1), 3
        )
        if b not in used
    )
    if fault == "empty_overlap":
        table["empty_blocks"] = [table["blocks"][0]["block"]]
    elif fault == "empty_order":
        table["empty_blocks"] = spare[:2][::-1]
    elif fault == "empty_parent":
        table["empty_blocks"] = [tables[-1]["blocks"][0]["block"]]
    elif fault == "empty_legacy":
        zero = root / f"golden/cells/{spare[0]}.parquet"
        pq.write_table(pq.read_schema(root / table["path"]).empty_table(), zero)
        manifest["tables"].append(
            dict(
                kind="cells",
                block=spare[0],
                path=zero.relative_to(root).as_posix(),
                rows=0,
                size=zero.stat().st_size,
                sha256=sha256(zero),
                empty_blocks=spare[1:2],
            )
        )
    elif fault == "order":
        table["blocks"].reverse()
    elif fault == "rows":
        table["blocks"][0]["rows"] += 1
        table["rows"] += 1
    elif fault == "parent":
        table["blocks"][-1]["block"] = tables[-1]["blocks"][0]["block"]
    elif fault == "duplicate":
        manifest["tables"].append(dict(table))
    elif fault == "mixed":
        table["block"] = table["blocks"][0]["block"]
    elif fault == "zero_rows":
        table["rows"] -= table["blocks"][0]["rows"]
        table["blocks"][0]["rows"] = 0
    elif fault in {"path_parent", "no_parent"}:
        replacement = (
            root
            / "cells"
            / (
                f"group={h3.cell_to_parent(tables[-1]['blocks'][0]['block'], 1)}"
                if fault == "path_parent"
                else "unlabelled"
            )
            / "part.parquet"
        )
        replacement.parent.mkdir(parents=True)
        replacement.write_bytes((root / table["path"]).read_bytes())
        table["path"] = replacement.relative_to(root).as_posix()
    else:
        table["blocks"].pop()
        table["rows"] = sum(b["rows"] for b in table["blocks"])
    path.write_text(json.dumps(manifest))
    output = tmp_path / "output"
    with pytest.raises(WriterInputError):
        _core.write_pack(str(path.parent), "core", str(output), options)
    assert not output.exists()


def test_captured_my_sg_manifest_and_empty_pipeline_group(tmp_path: Path) -> None:
    """Real package-5 routing, with synthetic rows; no real data needed by pytest."""
    root = tmp_path / "dataset"
    path, manifest, options = setup(root)
    capture = json.loads((FIXTURES / "dataset-my-sg-cells.json").read_text())
    recorded = json.loads(
        (
            FIXTURES.parents[1]
            / "tests/benchmarks/measurements"
            / "CLIENT_RELEASE_MEASUREMENTS.json"
        ).read_text()
    )
    assert capture["manifest_sha256"] == recorded["dataset"]["manifest_sha256"]
    original = next(t for t in manifest["tables"] if t["kind"] == "cells")
    sample = pq.ParquetFile(root / original["path"]).read()
    template = sample.to_pylist()[0]
    cells = capture["tables"]
    for table in cells:
        target = root / table["path"]
        target.parent.mkdir(parents=True)
        with pq.ParquetWriter(target, sample.schema) as writer:
            for entry in table["blocks"]:
                keys = sorted(h3.cell_to_children(entry["block"], 8))[: entry["rows"]]
                rows = [
                    template
                    | {"h3": key, "h3_uint64": h3.str_to_int(key), "h3_resolution": 8}
                    for key in keys
                ]
                writer.write_table(pa.Table.from_pylist(rows, schema=sample.schema))
        # The captured routing is unchanged; only synthetic payload identity differs.
        table.update(size=target.stat().st_size, sha256=sha256(target))
    empty = root / "cells/group=811fbffffffffff/part.parquet"
    empty.parent.mkdir(parents=True)
    with pq.ParquetWriter(empty, sample.schema):
        pass
    assert pq.ParquetFile(empty).num_row_groups == 0
    empty_entry = dict(
        kind="cells",
        path=empty.relative_to(root).as_posix(),
        blocks=[],
        rows=0,
        size=empty.stat().st_size,
        sha256=sha256(empty),
    )
    manifest["tables"] = (
        [t for t in manifest["tables"] if t["kind"] != "cells"] + cells + [empty_entry]
    )
    path.write_text(json.dumps(manifest))
    output = tmp_path / "output"
    result = _core.write_pack(str(path.parent), "core", str(output), options)
    # Grouping by size: every captured block shares one cells shard.
    assert sum(f["kind"] == "cells" for f in result["files"]) == 1
    assert _core.verify_pack(str(output))["family"] == "core"
    # An empty index may not hide a physical row group or a nonzero file count.
    for row_count in (0, 1):
        if row_count == 0:
            pq.write_table(sample.slice(0, 0), empty)
            assert pq.ParquetFile(empty).num_row_groups == 1
        else:
            with pq.ParquetWriter(empty, sample.schema):
                pass
        empty_entry.update(
            rows=row_count, size=empty.stat().st_size, sha256=sha256(empty)
        )
        path.write_text(json.dumps(manifest))
        with pytest.raises(WriterInputError):
            _core.write_pack(
                str(path.parent), "core", str(tmp_path / f"bad-{row_count}"), options
            )
