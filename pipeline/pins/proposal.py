"""Build reviewable source proposals and a compact file-level change report."""

import importlib
from dataclasses import asdict
from typing import Any, cast

from pipeline.config.schema import Config
from pipeline.runtime.jsonio import digest
from pipeline.sources.contract import Source
from pipeline.sources.proposals.http import Custody, keeping

from .models import SourcePin


def upstream(
    config: Config, names: list[str], custody: Custody
) -> dict[str, SourcePin]:
    """Propose each source, keeping every payload it hashes in `custody`."""
    result = {}
    for name in names:
        if name not in config.sources:
            raise ValueError(f"Unknown source: {name}")
        settings = config.sources[name]
        adapter = cast(Source, importlib.import_module(settings.adapter))
        with keeping(custody):
            result[name] = adapter.propose(settings)
        result[name].validate()
    return result


def stable(pin: SourcePin) -> dict[str, Any]:
    return {key: value for key, value in asdict(pin).items() if key != "pinned_at"}


def merge(
    previous: dict[str, SourcePin], proposed: dict[str, SourcePin], names: list[str]
) -> tuple[dict[str, SourcePin], dict[str, Any]]:
    result = dict(previous)
    changes = {}
    for name in names:
        if name not in proposed:
            raise ValueError(f"No candidate pin for source: {name}")
        before = previous.get(name)
        after = proposed[name]
        if before is not None and stable(before) == stable(after):
            after = before  # Inspection time alone must not invalidate a source.
        old_files = {item.name: asdict(item) for item in before.files} if before else {}
        new_files = {item.name: asdict(item) for item in after.files}
        changes[name] = {
            "changed": before != after,
            "old_release": before.release if before else None,
            "new_release": after.release,
            "old_digest": digest(asdict(before)) if before else None,
            "new_digest": digest(asdict(after)),
            "added": sorted(new_files.keys() - old_files.keys()),
            "removed": sorted(old_files.keys() - new_files.keys()),
            "changed_files": sorted(
                key
                for key in old_files.keys() & new_files.keys()
                if old_files[key] != new_files[key]
            ),
            "files": len(after.files),
            "bytes": sum(item.size for item in after.files),
        }
        result[name] = after
    return result, changes
