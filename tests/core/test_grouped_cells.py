"""Grouped Parquet routes must preserve the legacy block pack byte for byte."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import h3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from thereabouts import Geocoder, WriterInputError, _core
from thereabouts.store_files import sha256
from tools.synthetic_dataset import golden

FIXTURES = Path(__file__).parents[1] / "fixtures"


def setup(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    manifest_path, _ = golden(root)
    manifest = json.loads(manifest_path.read_text())
    cells = [t for t in manifest["tables"] if t["kind"] == "cells"]
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
    for parent, tables in sorted(groups.items()):
        tables.sort(key=lambda t: t["block"])
        path = root / f"golden/cells/group={parent}/part.parquet"
        path.parent.mkdir(parents=True)
        schema = pq.ParquetFile(root / tables[0]["path"]).schema_arrow
        with pq.ParquetWriter(path, schema) as writer:
            for table in tables:
                writer.write_table(pq.ParquetFile(root / table["path"]).read())
        assert pq.ParquetFile(path).num_row_groups == len(tables)
        grouped.append(
            dict(
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
        )
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
    assert any(b["rows"] == 0 for t in grouped for b in t["blocks"])
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


@pytest.mark.parametrize(
    "fault", ["order", "rows", "parent", "duplicate", "mixed", "missing_group"]
)
def test_grouped_manifest_routing_is_validated(tmp_path: Path, fault: str) -> None:
    root = tmp_path / "dataset"
    path, manifest, options = setup(root)
    tables = coalesce(root, manifest)
    table = next(t for t in tables if len(t["blocks"]) > 1)
    if fault == "order":
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
    else:
        table["blocks"].pop()
        table["rows"] = sum(b["rows"] for b in table["blocks"])
    path.write_text(json.dumps(manifest))
    output = tmp_path / "output"
    with pytest.raises(WriterInputError):
        _core.write_pack(str(path.parent), "core", str(output), options)
    assert not output.exists()
