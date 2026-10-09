"""Publish source inventories and manifests using workspace-relative records."""

from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from pipeline import files
from pipeline.config.sources import normalize_settings
from pipeline.runtime.jsonio import write_json
from pipeline.sources.contract import SourceContext


def file_record(ctx: SourceContext, path: Path) -> dict[str, Any]:
    """Kept for plate_country until it calls `files.file_record(ctx.root, ...)`."""
    return files.file_record(ctx.root, path)


def inventory_path(ctx: SourceContext) -> Path:
    return ctx.input(str(ctx.pin.metadata.get("inventory_name", "inventory.json")))


def cache(ctx: SourceContext, path: Path) -> bool:
    """Work files other than JSON reports are rebuilt by every run of the unit."""
    return path.is_relative_to(ctx.work) and path.suffix not in {".json", ".jsonl"}


def finish(
    ctx: SourceContext, partitions: list[Path], auxiliary: list[Path]
) -> list[Path]:
    """Record partitions and evidence; regenerable caches are neither recorded
    outputs nor manifest entries, so their absence never forces a restore."""
    evidence = [path for path in auxiliary if not cache(ctx, path)]
    records = []
    rows: dict[str, int] = {}
    sizes: dict[str, int] = {}
    for path in sorted(partitions):
        kind = path.relative_to(ctx.normalized).parts[0]
        count = pq.ParquetFile(path).metadata.num_rows
        records.append(
            {**files.file_record(ctx.root, path), "kind": kind, "rows": count}
        )
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
            "inventory": files.file_record(ctx.root, inventory_path(ctx)),
            "inputs": [
                files.file_record(ctx.root, ctx.input(item.name))
                for item in ctx.pin.files
            ],
            "partitions": records,
            "auxiliary": [files.file_record(ctx.root, path) for path in evidence],
            "rows": rows,
            "bytes": sizes,
            "configuration": normalize_settings(ctx.settings),
        },
    )
    return [*partitions, *evidence, manifest]
