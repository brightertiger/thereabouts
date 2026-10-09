"""The pinned document inventory as a partition, so plate tables built from these
documents depend on their digests through the normalized partitions alone."""

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.runtime.jsonio import atomic_output
from pipeline.sources.contract import SourceContext

KIND = "plate_documents"
SCHEMA = pa.schema(
    [
        pa.field("name", pa.string(), False),
        pa.field("path", pa.string(), False),
        pa.field("sha256", pa.string(), False),
        pa.field("url", pa.string(), False),
        pa.field("retrieved_at", pa.string(), False),
        pa.field("metadata", pa.string(), False),
    ]
)


def write(ctx: SourceContext, files: dict[str, dict[str, Any]]) -> Path:
    """One row per pinned file: its raw path, digest, URL and pin metadata."""
    rows = [
        {
            "name": name,
            "path": ctx.relative(Path(item["path"])),
            "sha256": item["sha256"],
            "url": item["url"],
            "retrieved_at": item["retrieved_at"],
            "metadata": json.dumps(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"path", "sha256", "url", "retrieved_at"}
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
        for name, item in sorted(files.items())
    ]
    path = ctx.ensure(
        ctx.normalized / KIND / ctx.unit.inputs_hash / "documents.parquet"
    )
    with atomic_output(path) as temporary:
        pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), temporary)
    return path
