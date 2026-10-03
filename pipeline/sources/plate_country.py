"""Inventory frozen plate-country evidence for the downstream inference stage."""

from pathlib import Path

from pipeline.config.source_options import Text as Options
from pipeline.runtime.jsonio import write_json

from .contract import SourceContext
from .shared.manifest import file_record, finish

__all__ = ["Options", "normalize"]


def normalize(ctx: SourceContext) -> list[Path]:
    records = [
        {
            "name": pin.metadata.get("key", pin.name),
            **file_record(ctx, ctx.input(pin.name)),
            "upstream": pin.metadata,
        }
        for pin in ctx.pin.files
    ]
    output = ctx.normalized / "evidence" / ctx.unit.inputs_hash / "sources.json"
    write_json(ctx.ensure(output), {"sources": records})
    return finish(ctx, [], [output])
