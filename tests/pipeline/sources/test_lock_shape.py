"""The committed lock is exactly what the proposers produce for unchanged bytes."""

import importlib
from typing import Any, cast

import pytest

from pipeline.config import load
from pipeline.pins.cli import LOCK, payloads
from pipeline.pins.lock import read_lock
from pipeline.pins.models import SourcePin
from pipeline.pins.proposal import merge
from pipeline.runtime.jsonio import digest
from pipeline.sources.contract import Source

from .replay import replay

# The pinned bytes before the lock was rewritten into proposer shape (2026-10-09):
# the digest of every source's (url, size, sha256, etag, last_modified) records,
# plus the plate_country pin added on 2026-10-10.
PAYLOADS = "dc79ca875343df42c8e0c5475434b2307741ddd461137f2134529da129041d9c"

SOURCES = sorted(name for name, source in load().sources.items() if source.enabled)


def facts(name: str, pin: SourcePin) -> dict[str, Any]:
    """Upstream release identifiers as the proposer recorded them in the pin."""
    return {
        "month": pin.release if name == "dbip" else "2026-10",
        **pin.metadata.get("releases", {}),
        "country_reference_sha256": pin.metadata.get("country_reference_sha256"),
    }


@pytest.mark.parametrize("name", SOURCES)
def test_unchanged_upstream_proposal_keeps_the_committed_pin(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = read_lock(LOCK)
    settings = load().sources[name]
    pin = lock[name]
    replay(pin, settings, facts(name, pin)).install(monkeypatch)
    adapter = cast(Source, importlib.import_module(settings.adapter))
    proposal = adapter.propose(settings)
    merged, changes = merge({name: pin}, {name: proposal}, [name])
    assert changes[name]["changed"] is False, changes[name]
    assert merged[name] is pin


def test_rewrite_kept_every_pinned_payload() -> None:
    lock = read_lock(LOCK)
    assert digest({name: payloads(pin) for name, pin in lock.items()}) == PAYLOADS
