"""Inventory frozen plate-country evidence for the downstream inference stage."""

from pathlib import Path

from pipeline.config.source_options import Text as Options
from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin
from pipeline.runtime.jsonio import write_json

from .contract import SourceContext
from .proposals.plates import propose as propose_pin
from .shared.manifest import file_record, finish

__all__ = ["Options", "normalize", "propose"]


def normalize(ctx: SourceContext) -> list[Path]:
    records = [
        {
            "name": pin.metadata.get("key", pin.name),
            **file_record(ctx, ctx.input(pin.name)),
            "url": pin.url,
            "retrieved_at": ctx.pin.pinned_at,
            "upstream": pin.metadata,
        }
        for pin in ctx.pin.files
    ]
    output = ctx.normalized / "evidence" / ctx.unit.inputs_hash / "sources.json"
    write_json(ctx.ensure(output), {"sources": records})
    return finish(ctx, [], [output])


def propose(settings: SourceSettings) -> SourcePin:
    """Pin the reviewed inventory's documents that the plates pin lacks."""
    return propose_pin(settings)
