"""Resolve completed artifacts into temporary engine views; persist relative paths."""

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from pipeline.engines.reconcile.common import Row
from pipeline.runtime.paths import located
from pipeline.runtime.records import Output

from .contract import Context
from .engine_data import read


def outputs(ctx: Context, stage: str, key: str) -> tuple[Output, ...]:
    record = ctx.ledger.get(stage, key)
    if record is None:
        raise ValueError(f"Missing completed input: {stage}/{key}")
    return record.outputs


def artifact(ctx: Context, stage: str, key: str, *, suffix: str) -> Path:
    matches = [
        record for record in outputs(ctx, stage, key) if record.path.endswith(suffix)
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one {suffix} input for {stage}/{key}")
    return located(ctx.root, matches[0].path)


def receipt(ctx: Context, stage: str, key: str, *, suffix: str) -> Row:
    path = artifact(ctx, stage, key, suffix=suffix)
    return read(ctx, path.relative_to(ctx.root).as_posix())


def table(ctx: Context, stage: str, key: str, kind: str, **labels: str) -> Row:
    records = [
        record
        for record in outputs(ctx, stage, key)
        if record.path.endswith(".parquet")
    ]
    if len(records) != 1:
        records = [
            record
            for record in records
            if kind in Path(record.path).parts or Path(record.path).stem == kind
        ]
    if len(records) != 1:
        raise ValueError(f"Expected one {kind} table for {stage}/{key}")
    record = records[0]
    return {
        **asdict(record),
        "kind": kind,
        "rows": pq.read_metadata(located(ctx.root, record.path)).num_rows,
        **labels,
    }


def local(ctx: Context, value: Any) -> Any:
    """Materialize path fields only in memory; never write this view as metadata."""
    if isinstance(value, dict):
        return {
            key: str(located(ctx.root, item))
            if key == "path" and isinstance(item, str)
            else local(ctx, item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [local(ctx, item) for item in value]
    return value
