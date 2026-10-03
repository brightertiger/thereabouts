"""Publish source inventories and manifests using workspace-relative records."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from pipeline.runtime.jsonio import sha256_file, write_json
from pipeline.sources.contract import SourceContext


def file_record(ctx: SourceContext, path: Path) -> dict[str, Any]:
    return {
        "path": ctx.relative(path),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def inventory_path(ctx: SourceContext) -> Path:
    return ctx.input(str(ctx.pin.metadata.get("inventory_name", "inventory.json")))


def finish(
    ctx: SourceContext, partitions: list[Path], auxiliary: list[Path]
) -> list[Path]:
    records = []
    rows: dict[str, int] = {}
    sizes: dict[str, int] = {}
    for path in sorted(partitions):
        kind = path.relative_to(ctx.normalized).parts[0]
        count = pq.ParquetFile(path).metadata.num_rows
        records.append({**file_record(ctx, path), "kind": kind, "rows": count})
        rows[kind] = rows.get(kind, 0) + count
        sizes[kind] = sizes.get(kind, 0) + path.stat().st_size
    manifest = ctx.ensure(ctx.normalized / "manifest.json")
    write_json(
        manifest,
        {
            "manifest_version": 1,
            "schema_version": "1",
            "source": ctx.settings.name,
            "source_release": ctx.pin.release,
            "inventory": file_record(ctx, inventory_path(ctx)),
            "inputs": [
                file_record(ctx, ctx.input(item.name)) for item in ctx.pin.files
            ],
            "partitions": records,
            "auxiliary": [file_record(ctx, path) for path in auxiliary],
            "rows": rows,
            "bytes": sizes,
            "configuration": asdict(ctx.settings),
            "units": [
                {
                    "stage": ctx.unit.recipe.stage,
                    "unit_id": ctx.unit.recipe.unit_id,
                    "inputs_hash": ctx.unit.inputs_hash,
                }
            ],
        },
    )
    return [*partitions, *auxiliary, manifest]
