"""Opt-in, read-only world proof plus real application to copied JSON and ledger."""

import os
import shutil
import time
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.migration.adoption import simulate
from pipeline.migration.apply import apply
from pipeline.migration.command import migrate
from pipeline.migration.handover import prepare
from pipeline.migration.handover_apply import apply_handover
from pipeline.runtime.context import context
from pipeline.runtime.jsonio import sha256_file, write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import counts, plan
from pipeline.runtime.resources import ResourceGuard, workspace_bytes
from pipeline.runtime.verification import Verifier
from pipeline.stages.registry import registry

from .helpers import peak_rss, retained_stages


@pytest.mark.world
def test_world_copy_application(tmp_path: Path) -> None:
    value = os.environ.get("THEREABOUTS_PIPELINE_DATA")
    if not value:
        pytest.skip("set THEREABOUTS_PIPELINE_DATA for read-only world adoption")
    repository = Path(__file__).parents[2]
    assert tmp_path.is_relative_to(repository), "Use --basetemp inside this worktree"
    root = Path(value)
    original_ledger = root / "work/ledger.sqlite3"
    digest = sha256_file(original_ledger)
    modified = original_ledger.stat().st_mtime_ns
    config = load()
    stages = registry(config)
    started = time.monotonic()
    with Ledger(root, original_ledger) as source:
        migration = simulate(root, source, config, retained_stages())
    try:
        assert all(d.state == "current" for d in migration.decisions)
        copied = tmp_path / "copied-metadata"
        copied_ledger = copied / "work/ledger.sqlite3"
        # Check before any copy; no Parquet tree or hard link is created.
        needed = (
            2 * original_ledger.stat().st_size
            + sum(len(data) for data in migration.rewrites.before.values())
            + int(
                migration.context.ledger.db.execute("PRAGMA page_count").fetchone()[0]
            )
            * int(migration.context.ledger.db.execute("PRAGMA page_size").fetchone()[0])
        )
        needed += 2 * sum(len(data) for data in migration.rewrites.before.values())
        needed += sum(len(data) for data in migration.rewrites.after.values())
        assert workspace_bytes(repository) + needed < 3_000_000_000
        assert shutil.disk_usage(tmp_path).free - needed >= config.resources.disk_floor
        copied_ledger.parent.mkdir(parents=True)
        shutil.copy2(original_ledger, copied_ledger)
        for name, data in migration.rewrites.before.items():
            target = copied / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        copied_context = replace(
            migration.context,
            root=copied,
            guard=ResourceGuard(copied, config.resources),
        )
        proposal = replace(migration, context=copied_context)
        with Ledger(copied, copied_ledger) as source_copy:
            apply(proposal, source_copy, copied_ledger)
        assert not list(copied.rglob("*.parquet"))
        assert sha256_file(copied / "work/ledger.pre-migration.sqlite3") == digest
        overlay = {
            name: (copied / name).read_bytes() for name in migration.rewrites.after
        }
        with Ledger(root, copied_ledger) as adopted:
            ctx = replace(
                context(config, root, adopted), verifier=Verifier(root, overlay)
            )
            handover = prepare(ctx, stages)
            try:
                assert all(d.state == "current" for d in handover.decisions)
                assert len(handover.changes) == 26
                before_outputs = {
                    record.key: record.outputs for record in adopted.records()
                }
                apply_handover(handover, adopted)
            finally:
                handover.context.ledger.close()
        with Ledger(root, copied_ledger) as adopted:
            ctx = replace(
                context(config, root, adopted), verifier=Verifier(root, overlay)
            )
            assert {
                record.key: record.outputs for record in adopted.records()
            } == before_outputs
            decisions = plan(ctx, stages)
            assert all(d.state == "current" for d in decisions)
            before = sha256_file(copied_ledger)
            assert migrate(ctx, stages, "all", True, tmp_path / "idempotence.json") == 0
            assert sha256_file(copied_ledger) == before
        assert sha256_file(original_ledger) == digest
        assert original_ledger.stat().st_mtime_ns == modified
        assert all(
            (root / name).read_bytes() == payload
            for name, payload in migration.rewrites.before.items()
        )
        write_json(
            tmp_path / "measurements.json",
            {
                "seconds": time.monotonic() - started,
                "peak_rss_bytes": peak_rss(),
                "copied_ledger_bytes": copied_ledger.stat().st_size,
                "copied_json_bytes": sum(len(payload) for payload in overlay.values()),
                "stages": counts(decisions),
                "real_ledger_sha256": digest,
            },
        )
    finally:
        migration.context.ledger.close()
