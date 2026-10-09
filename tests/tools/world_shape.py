"""A world-shaped core dataset: 14,847 stored r3 blocks and a multi-shard catalogue.

The 2026.10 world stores 14,847 of the 41,162 r3 blocks and about 5.9 M catalogue
places. This copy of the committed core-synthetic dataset keeps that block count,
spread over every r1 group in the grouped layout, and adds enough places with
padded evidence that the catalogue spans several shards at the default 32 MiB
target. It writes with the real writer and the core-synthetic options.
"""

import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import h3
import pyarrow as pa
import pyarrow.parquet as pq

from tests.tools.build_sample_pack import sha
from thereabouts import _core

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TEMPLATE = FIXTURES / "datasets/core-synthetic"
WORLD_BLOCKS = 14_847


def blocks() -> list[str]:
    """World-count r3 blocks spread evenly over all of them, ascending."""
    every = sorted(
        cell for base in h3.get_res0_cells() for cell in h3.cell_to_children(base, 3)
    )
    return [every[i * len(every) // WORLD_BLOCKS] for i in range(WORLD_BLOCKS)]


def options(**extra: Any) -> dict[str, Any]:
    manifest = json.loads((FIXTURES / "packs/core-synthetic/manifest.json").read_text())
    return {**manifest["inputs"]["options"], **extra}


def _record(
    root: Path, path: Path, kind: str, rows: int, **fields: Any
) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": path.relative_to(root).as_posix(),
        "rows": rows,
        "size": path.stat().st_size,
        "sha256": sha(path),
        **fields,
    }


def _extend(path: Path, rows: list[dict[str, Any]]) -> int:
    table = pq.read_table(path)
    combined = table.to_pylist() + rows
    pq.write_table(pa.Table.from_pylist(combined, schema=table.schema), path)
    return len(combined)


def dataset(root: Path, *, places: int, evidence_bytes: int) -> Path:
    """Write the dataset below ``root``; returns the directory holding manifest.json."""
    shutil.copytree(TEMPLATE, root)
    golden = root / "golden"
    manifest = json.loads((golden / "manifest.json").read_text())
    kept = [
        t
        for t in manifest["tables"]
        if t["kind"] not in {"places", "place_to_city", "cells"}
    ]
    template = next(
        row
        for row in pq.read_table(golden / "places/AA.parquet").to_pylist()
        if row["place_id"] == "city:synthetic:unused"
    )
    ids = [f"city:world:{i:07}" for i in range(places)]
    path = golden / "places/AA.parquet"
    count = _extend(
        path,
        [
            {
                **template,
                "place_id": place,
                "name": f"World {i}",
                "normalized_city_id": place,
                # Catalogue evidence carries source_ids verbatim: pad it to world size.
                "source_ids": json.dumps(
                    [{"source": "synthetic", "id": f"{place}:{'x' * evidence_bytes}"}]
                ),
            }
            for i, place in enumerate(ids)
        ],
    )
    kept.append(_record(root, path, "places", count, country="AA"))
    path = golden / "place_to_city/AA.parquet"
    count = _extend(
        path,
        [
            {"place_id": p, "city_id": p, "method": "self", "evidence": None}
            for p in ids
        ],
    )
    kept.append(_record(root, path, "place_to_city", count))
    cells = pq.read_table(golden / "cells/830800fffffffff.parquet")
    row = cells.to_pylist()[0]
    shutil.rmtree(golden / "cells")
    groups: dict[str, list[str]] = defaultdict(list)
    for block in blocks():
        groups[h3.cell_to_parent(block, 1)].append(block)
    stored = 0
    for parent, members in sorted(groups.items()):
        path = golden / f"cells/group={parent}/part.parquet"
        path.parent.mkdir(parents=True)
        with pq.ParquetWriter(path, cells.schema) as writer:
            for block in members:
                # One whole-block row per block, each naming its own city.
                value = {
                    **row,
                    "h3": block,
                    "h3_uint64": h3.str_to_int(block),
                    "city_id": ids[stored % places],
                }
                writer.write_table(pa.Table.from_pylist([value], schema=cells.schema))
                stored += 1
        kept.append(
            _record(
                root,
                path,
                "cells",
                len(members),
                blocks=[
                    {"block": block, "row_group": i, "rows": 1}
                    for i, block in enumerate(members)
                ],
            )
        )
    manifest["tables"] = kept
    (golden / "manifest.json").write_text(json.dumps(manifest))
    return golden


def release(pack: Path, root: Path) -> Path:
    """A format-3 release directory holding one core archive."""
    root.mkdir(parents=True)
    archive = root / f"core{_core.ARCHIVE_SUFFIX}"
    created = _core.archive_pack(str(pack), str(archive))
    manifest = json.loads((pack / "manifest.json").read_text())
    entry = {"url": archive.name, **created, "format_minor": manifest["format_minor"]}
    index = {
        "format": _core.INDEX_FORMAT,
        "datasets": {manifest["data_version"]: {"packs": {"core": entry}}},
    }
    (root / "index.json").write_text(json.dumps(index))
    return root
