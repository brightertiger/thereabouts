"""Verify retained outputs, then simulate new identities in an in-memory ledger."""

import hashlib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pipeline.config import Config
from pipeline.runtime.jsonio import JSON, Object, sha256_file
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import Decision, counts, order_units, plan
from pipeline.runtime.records import Completion, Recipe
from pipeline.runtime.resources import ResourceGuard
from pipeline.runtime.verification import Verifier
from pipeline.stages.contract import Context, Stage, make_unit

from .backup import original_hash
from .candidates import Candidate, collect, parameters
from .dependencies import dependencies
from .evidence import add_evidence
from .inventory import Inventory
from .repair_report import file_class, in_spec, summarize
from .rewrites import Rewrites, prepare

ABSENT_RECONCILE_PREFIXES = ("reconciled/", "work/reconcile/")


@dataclass
class Migration:
    context: Context
    rewrites: Rewrites
    report: Object
    decisions: list[Decision]


def _verify(candidate: Candidate, verifier: Verifier) -> None:
    for output in candidate.outputs.values():
        problem = verifier.problem(output)
        if problem is None:
            continue
        missing = problem.startswith("output missing:")
        if (
            missing
            and candidate.stage == "reconcile"
            and output.path.startswith(ABSENT_RECONCILE_PREFIXES)
        ) or (
            missing
            and candidate.stage == "download"
            and candidate.custody
            and output.path.startswith(f"raw/{candidate.unit_id}/")
        ):
            candidate.absent.append(output.path)
        else:
            raise ValueError(f"Cannot adopt {candidate.key}: {problem}")


def simulate(
    root: Path,
    source: Ledger,
    config: Config,
    stages: Sequence[Stage],
    *,
    log: Callable[[str], None] = print,
) -> Migration:
    if source.migrated:
        raise ValueError("Ledger is already migrated; use plan or migrate check")
    ledger_hash = sha256_file(source.path) if source.path else None
    log("migration: reading active manifests and mapping legacy units")
    inventory = Inventory.read(root)
    for manifest in (inventory.base, inventory.active):
        if manifest and (
            manifest.get("block_resolution") != config.h3.block_resolution
            or manifest.get("reference_resolution") != config.h3.cell_resolution
        ):
            raise ValueError(
                "Cannot adopt a different H3 encoding; keep the recorded resolutions"
            )
    candidates, changes = collect(source, inventory)
    add_evidence(inventory, candidates)
    log(f"migration: verifying {len(candidates)} adopted units")
    verifier = Verifier(root, inventory.imports)
    for candidate in candidates.values():
        _verify(candidate, verifier)
    log("migration: preparing portable JSON metadata")
    for change in changes:
        for relocation in cast(list[JSON], change.get("relocations", [])):
            if isinstance(relocation, dict):
                inventory.aliases[str(relocation["from"])] = str(relocation["to"])
    rewrites = prepare(inventory, candidates)
    ledger = Ledger(root, None, readonly=False)
    ctx = Context(
        config,
        root,
        ledger,
        ResourceGuard(root, config.resources),
        Verifier(root, rewrites.after),
        storage=config.storage,
    )
    log("migration: deriving stage identities and input dependencies")
    identities = {stage.name: stage.identity(ctx) for stage in stages}
    groups: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {}
    recipes = [
        Recipe(c.stage, c.unit_id, parameters(c), dependencies(c, candidates, groups))
        for c in candidates.values()
    ]
    units = order_units(
        [make_unit(ctx, recipe, identities[recipe.stage]) for recipe in recipes]
    )
    with ledger.transaction():
        for initial in units:
            unit = make_unit(ctx, initial.recipe, initial.identity)
            candidate = candidates[unit.key]
            outputs = tuple(rewrites.output(o) for o in candidate.outputs.values())
            metadata: Object = {
                "identity": unit.identity,
                "dependency_hash": unit.dependency_hash,
                "adopted": True,
                "legacy_receipts": list(candidate.inputs),
                "outputs_absent": bool(candidate.absent),
                "absent_paths": list(candidate.absent),
            }
            if candidate.custody:
                metadata.update(custody=candidate.custody, remote_verified=False)
            ledger.register(unit.recipe)
            ledger.store(
                Completion(
                    *unit.key,
                    unit.inputs_hash,
                    outputs,
                    metadata,
                    datetime.now(UTC).isoformat(),
                )
            )
    # Reuse only hashes just read in this simulation, never across commands.
    ctx.verifier.cache = verifier.cache
    log("migration: checking the simulated ledger")
    decisions = plan(ctx, stages)
    invalid = [d for d in decisions if d.state != "current"]
    if invalid:
        ledger.close()
        raise ValueError(f"Adoption produced noncurrent units: {invalid[:5]}")
    rewrite_details: list[Object] = []
    for name, data in rewrites.after.items():
        rewrite_details.append(
            {
                "path": name,
                "class": file_class(name, created=name not in rewrites.before),
                "in_spec": in_spec(name),
                "repairs": {
                    key: count
                    for key, count in rewrites.statistics.get(name, {}).items()
                },
                "before": hashlib.sha256(rewrites.before[name]).hexdigest()
                if name in rewrites.before
                else None,
                "after": hashlib.sha256(data).hexdigest(),
                "before_bytes": len(rewrites.before.get(name, b"")),
                "after_bytes": len(data),
            }
        )
    report: Object = {
        "mode": "simulation",
        "ledger_sha256": ledger_hash,
        "original_ledger_sha256": original_hash(source),
        "identities": {name: value for name, value in identities.items()},
        "unit_inputs": [
            {
                "stage": record.stage,
                "unit": record.unit_id,
                "inputs_hash": record.inputs_hash,
            }
            for record in ledger.records()
        ],
        "legacy_rows": len(changes),
        "adopted_units": len(candidates),
        "dropped_rows": sum(change["stage"] is None for change in changes),
        "json_files_changed": len(rewrites.before),
        "json_files_created": len(rewrites.after) - len(rewrites.before),
        "outputs_absent_units": sum(bool(c.absent) for c in candidates.values()),
        "outputs_absent_files": sum(len(c.absent) for c in candidates.values()),
        "absent_paths_by_prefix": {
            prefix: count
            for prefix, count in Counter(
                next(
                    (
                        prefix
                        for prefix in ABSENT_RECONCILE_PREFIXES
                        if path.startswith(prefix)
                    ),
                    f"raw/{candidate.unit_id}/",
                )
                for candidate in candidates.values()
                for path in candidate.absent
            ).items()
        },
        "offloaded_sources": [name for name in sorted(inventory.offloaded)],
        "remote_verified": False,
        "bytes_hashed": verifier.bytes_hashed,
        "stages": {name: dict(value) for name, value in counts(decisions).items()},
        "changes": [change for change in changes],
        "json_changes": [item for item in rewrite_details],
        "metadata_repairs": summarize(rewrite_details),
    }
    return Migration(ctx, rewrites, report, decisions)
