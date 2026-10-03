"""Run explicit source extraction, country reconciliation and quality units."""

import copy
import json
from collections import Counter
from pathlib import Path
from typing import cast

from pipeline.engines.reconcile import build, catalog, inputs, land, quality
from pipeline.engines.reconcile.common import Row, connect
from pipeline.engines.reconcile.lookup import Locator
from pipeline.engines.storage import file_record
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.paths import located

from . import engine_io as io
from .contract import Context, Unit
from .engine_data import countries, source_manifest


def country_paths(ctx: Context, codes: list[str]) -> dict[str, Path]:
    return {
        cc: io.artifact(ctx, "reconcile", "country/" + cc, suffix=".sqlite")
        for cc in codes
    }


def country_policy(path: Path) -> Row:
    db = connect(path, readonly=True)
    try:
        value = db.execute("SELECT data FROM metadata WHERE key='policy'").fetchone()
        if value is None:
            raise ValueError("Country database lacks its resolved policy")
        result: Row = json.loads(value[0])
        return result
    finally:
        db.close()


def normalized_paths(ctx: Context, sources: list[str]) -> dict[str, list[str]]:
    result = {}
    for source in sources:
        manifest = source_manifest(ctx, source)
        if manifest is None:
            raise ValueError(f"Missing normalized source: {source}")
        for kind in ctx.config.engines.reconcile_sources[source]:
            result[f"{source}_{kind}"] = [
                str(located(ctx.root, record["path"]))
                for record in manifest["partitions"]
                if record["kind"] == kind
            ]
    return result


def run(ctx: Context, unit: Unit) -> list[Path]:
    action, _, key = unit.recipe.unit_id.partition("/")
    policy = copy.deepcopy(cast(Row, unit.recipe.parameters["policy"]))
    limits = ctx.config.engines.limits
    root = located(ctx.root, ctx.config.paths.reconciled)
    work = located(ctx.root, ctx.config.paths.work) / "reconcile" / unit.inputs_hash
    target = root / unit.inputs_hash
    if action == "extract":
        sources = [d.unit_id for d in unit.recipe.dependencies]
        work.mkdir(parents=True, exist_ok=True)
        db = inputs.query_engine(
            normalized_paths(ctx, sources), work, ctx.config.resources, limits
        )
        try:
            inputs.sovereigns(db, policy)
            extracted_paths = inputs.extract(db, key, work / key, limits)
        finally:
            db.close()
        path = work / key / "policy.json"
        write_json(path, policy)
        return [*extracted_paths, path]
    if action == "links":
        extracted = io.artifact(
            ctx, "reconcile", "extract/" + key, suffix="policy.json"
        ).parent
        return [
            catalog.catalog(extracted, work / f"{key}-links.sqlite", policy, limits)
        ]
    if action == "country":
        extracted = io.artifact(
            ctx, "reconcile", "extract/" + key, suffix="policy.json"
        )
        policy = io.receipt(ctx, "reconcile", "extract/" + key, suffix="policy.json")
        source = io.artifact(ctx, "reconcile", "links/" + key, suffix=".sqlite")
        return [
            build.build_country(
                source, extracted.parent, target / f"{key}.sqlite", key, policy, limits
            )
        ]
    if action == "land":
        manifest = source_manifest(ctx, "osm_land")
        if manifest is None:
            raise ValueError("Missing normalized physical land")
        return [
            land.build_land(
                ctx.root,
                [r["path"] for r in manifest["partitions"] if r["kind"] == "areas"],
                target / "land.sqlite",
                limits,
            )
        ]
    codes = countries(ctx)
    paths = country_paths(ctx, codes)
    physical = io.artifact(ctx, "reconcile", "land/world", suffix=".sqlite")
    if paths:
        policy = country_policy(next(iter(paths.values())))
    if action == "quality":
        with Locator(paths, physical, policy, ctx.config.engines.limits) as oracle:
            report = quality.country_report(oracle, key, policy)
        destination = target / f"{key}-quality.json"
        write_json(destination, report)
        return [destination]
    reports = {
        cc: io.artifact(ctx, "reconcile", "quality/" + cc, suffix=".json")
        for cc in codes
    }
    if action == "gate":
        totals: Counter[str] = Counter()
        for cc in policy["pilot"]:
            if cc in reports:
                totals.update(
                    io.receipt(ctx, "reconcile", "quality/" + cc, suffix=".json")[
                        "large_places"
                    ]["counts"]
                )
        with Locator(paths, physical, policy, ctx.config.engines.limits) as oracle:
            named = quality.named_points(oracle)
        coverage = totals["answer"] / totals["total"] if totals["total"] else 0.0
        full = set(policy["pilot"]) <= set(paths)
        destination = root / "pilot.json"
        passed = (
            full
            and coverage >= ctx.config.engines.minimum_country_coverage
            and all(r["passed"] for r in named)
        )
        write_json(
            destination,
            {
                "passed": passed,
                "full_pilot": full,
                "coverage": coverage,
                "totals": dict(totals),
                "named": named,
                "policy": policy,
                "reports": {
                    cc: file_record(ctx.root, path) for cc, path in reports.items()
                },
            },
        )
        if not passed:
            raise ValueError(
                "Reconciliation pilot quality gate failed; "
                "inspect reconciled/pilot.json"
            )
        return [destination]
    if action == "manifest":
        gate = io.receipt(ctx, "reconcile", "gate/pilot", suffix="pilot.json")
        if not gate["passed"]:
            raise ValueError(
                "Cannot publish reconciliation before its quality gate passes"
            )
        destination = root / "manifest.json"
        write_json(
            destination,
            {
                "completed": True,
                "policy": policy,
                "countries": {
                    cc: file_record(ctx.root, path) for cc, path in paths.items()
                },
                "reports": {
                    cc: file_record(ctx.root, path) for cc, path in reports.items()
                },
                "land": file_record(ctx.root, physical),
            },
        )
        return [destination]
    raise ValueError(f"Unknown reconciliation action: {action}")


def finish(ctx: Context) -> None:
    record = ctx.ledger.get("reconcile", "gate/pilot")
    if record is None:
        return
    if record.metadata.get("outputs_absent"):
        return
    value = io.receipt(ctx, "reconcile", "gate/pilot", suffix="pilot.json")
    if not value["passed"]:
        raise ValueError(
            "Reconciliation pilot quality gate failed; inspect reconciled/pilot.json"
        )
