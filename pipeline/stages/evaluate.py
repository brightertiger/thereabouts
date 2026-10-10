"""Measure the frozen pilot and enforce policy-bound human review decisions."""

from dataclasses import asdict
from pathlib import Path
from typing import cast

from pipeline.config import policies, reviews
from pipeline.engines.artifacts import EVALUATION, read_json
from pipeline.engines.cells.reader import Cells
from pipeline.engines.cities.evaluate import Comparison
from pipeline.engines.cities.gates import failures, unreviewed
from pipeline.engines.cities.quality import country_report, named_checks
from pipeline.engines.store.codec import Row
from pipeline.engines.store.origins import resolver
from pipeline.files import file_record
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.paths import located

from . import cells, cities, development
from . import engine_io as io
from . import parameters as unit_parameters
from .contract import Context, Unit
from .engine_data import Geography, countries
from .engine_views import Engines


def run(ctx: Context, unit: Unit) -> list[Path]:
    policy = cast(Row, unit.recipe.parameters["policy"])
    settings = ctx.config.engines
    approval = reviews.load(located(REPOSITORY, settings.city_review), policy)
    base = io.receipt(ctx, "cells", "snapshot/current", suffix="manifest.json")
    codes = countries(ctx)
    if not base["completed"] or not set(policy["pilot"]) <= set(codes):
        raise ValueError(
            "Evaluation requires complete base cells and all pilot countries"
        )
    root = located(ctx.root, ctx.config.paths.work) / "evaluation" / unit.inputs_hash
    tables = io.local(ctx, base["tables"])
    reader = Cells(tables, ctx.config.engines.limits, grid=ctx.config.h3)
    centres = cities.urban(ctx)
    engines = Engines(ctx, codes, policy, centres)
    inputs = cells.inputs(ctx, codes, policy)
    comparison = Comparison(reader, engines, policy["town_radius"]["enabled"])
    reports, outputs = [], []
    probes = read_json(EVALUATION / "cities/probes.json")
    for cc in policy["pilot"]:
        report = country_report(comparison, cc, engines[cc], centres, probes)
        report["country"] = cc
        path = root / f"{cc}.json"
        write_json(path, report)
        reports.append(report)
        outputs.append(path)
    named = named_checks(comparison, inputs)
    failed = failures(reports, named)
    origins = resolver(
        lambda cc: io.artifact(ctx, "reconcile", "country/" + cc, suffix=".sqlite"),
        settings.limits.sqlite_cache_kib,
    )
    # Remaining losses carry their stable origins for the reviewer.
    failed["all_boundaries"] = [
        {**loss, "origins": origins(loss)}
        for loss in unreviewed(
            failed["all_boundaries"],
            [asdict(item) for item in approval.boundary_exceptions],
            origins,
        )
    ]
    score = development.score(
        ctx, located(REPOSITORY, settings.evaluation_points), tables, policy, codes
    )
    passed = (
        not any(failed.values())
        and score["after"]["counts"]["correct"] >= approval.minimum_dev_correct
    )
    path = root / "pilot.json"
    write_json(
        path,
        {
            "passed": passed,
            "policy_fingerprint": approval.policy_fingerprint,
            "review": asdict(approval),
            "countries": {
                report["country"]: file_record(ctx.root, item)
                for report, item in zip(reports, outputs, strict=True)
            },
            "named": named,
            "failed_spatial_gates": failed,
            "development": score,
        },
    )
    if not passed:
        raise ValueError(
            f"Pilot evaluation failed; inspect {path.relative_to(ctx.root)}"
        )
    return [path, *outputs]


def finish(ctx: Context) -> None:
    record = ctx.ledger.get("evaluate", "pilot")
    if record is not None and not record.metadata.get("adopted"):
        value = io.receipt(ctx, "evaluate", "pilot", suffix="pilot.json")
        if not value["passed"]:
            raise ValueError("Pilot evaluation has not passed")


def parameters(ctx: Context, geography: Geography) -> unit_parameters.Configure:
    policy = unit_parameters.cities(ctx)
    select = unit_parameters.constant(policy)
    review = policies.read(located(REPOSITORY, ctx.config.engines.city_review))
    limits = ctx.config.engines.limits
    return unit_parameters.prepare(
        select,
        geography,
        country_bytes=limits.country_reservation_bytes,
        block_bytes=limits.block_reservation_bytes,
        extra={"review": review},
        reads={
            "pilot": (
                *unit_parameters.CITY_EVIDENCE,
                ctx.config.engines.evaluation_points,
                ctx.config.engines.city_review,
            )
        },
    )
