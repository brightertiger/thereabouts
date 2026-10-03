"""Handover verifies independent discovery and cannot bless later code changes."""

from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.migration.adoption import simulate
from pipeline.migration.apply import apply
from pipeline.migration.handover import prepare
from pipeline.migration.handover_apply import apply_handover
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.stages.contract import Stage
from pipeline.stages.registry import registry

from .helpers import SyntheticStage, context, legacy_workspace


def adopted(root: Path) -> Path:
    path = legacy_workspace(root)
    with Ledger(root, path) as source:
        proposal = simulate(root, source, load(), registry(load()))
        try:
            apply(proposal, source, path)
        finally:
            proposal.context.ledger.close()
    return path


def ported() -> tuple[SyntheticStage, list[Stage]]:
    stage = SyntheticStage(
        "download", [Recipe("download", "ghsl", {"release": "fixture"})]
    )
    return stage, [stage, *registry(load())[1:]]


def test_handover_changes_only_identity_parameters_and_input_hash(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    path = adopted(root)
    stage, stages = ported()
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with Ledger(root, path) as source:
        original = source.get("download", "ghsl")
        assert original
        proposal = prepare(context(root, source), stages)
        try:
            assert all(d.state == "current" for d in proposal.decisions)
            assert proposal.changes == [("download", "ghsl")]
            changed = proposal.context.ledger.get("download", "ghsl")
            assert changed
            assert (
                replace(
                    changed,
                    inputs_hash=original.inputs_hash,
                    metadata=original.metadata,
                )
                == original
            )
            assert {k: v for k, v in changed.metadata.items() if k != "identity"} == {
                k: v for k, v in original.metadata.items() if k != "identity"
            }
            assert all(p.read_bytes() == payload for p, payload in before.items())
            apply_handover(proposal, source)
        finally:
            proposal.context.ledger.close()
    assert all(p.read_bytes() == payload for p, payload in before.items() if p != path)
    assert stage.calls == []
    with Ledger(root, path) as source:
        ctx = context(root, source)
        proposal = prepare(ctx, stages)
        try:
            assert proposal.changes == []
        finally:
            proposal.context.ledger.close()
        stage.implementation = "later code change"
        with pytest.raises(ValueError, match="already handed over"):
            prepare(ctx, stages)


@pytest.mark.parametrize("keys", [[], ["ghsl", "new"], ["ghsl", "ghsl"]])
def test_handover_refuses_changed_discovery(tmp_path: Path, keys: list[str]) -> None:
    root = tmp_path / "data"
    path = adopted(root)
    stage, stages = ported()
    stage.recipes = [Recipe("download", key) for key in keys]
    before = sha256_file(path)
    with Ledger(root, path) as source, pytest.raises(ValueError, match="key mismatch"):
        prepare(context(root, source), stages)
    assert sha256_file(path) == before


def test_handover_accepts_recorded_absence_but_rejects_corruption(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    path = adopted(root)
    raw = root / "raw/ghsl/input.zip"
    with Ledger(
        root, path, readonly=False, timeout=load().resources.ledger_timeout_seconds
    ) as ledger:
        record = ledger.get("download", "ghsl")
        assert record
        with ledger.transaction():
            ledger.store(
                replace(
                    record,
                    metadata={
                        **record.metadata,
                        "absent_paths": [raw.relative_to(root).as_posix()],
                    },
                )
            )
    raw.unlink()
    _, stages = ported()
    with Ledger(root, path) as source:
        proposal = prepare(context(root, source), stages)
        proposal.context.ledger.close()
        raw.write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="Cannot hand over"):
            prepare(context(root, source), stages)
