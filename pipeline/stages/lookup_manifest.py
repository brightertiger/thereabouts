"""Verify complete stored tables before exposing the normalized manifest."""

from collections import Counter
from dataclasses import asdict
from pathlib import Path

from pipeline.config import reviews
from pipeline.engines.artifact_io import file_record
from pipeline.engines.cells.metrics import measure
from pipeline.engines.cities.gates import failures, unreviewed
from pipeline.engines.names import build as names
from pipeline.engines.normalize_cells.references import reference_checks
from pipeline.engines.reconcile.common import Row
from pipeline.engines.store.origins import resolver
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.paths import located

from . import engine_io as io
from .contract import Context, Unit


def publish(ctx: Context, unit: Unit, root: Path, policy: Row) -> list[Path]:
    tables, reports, named = [], [], []
    for dep in unit.recipe.dependencies:
        action, _, key = dep.unit_id.partition("/")
        if dep.stage == "plate_country":
            receipt = io.receipt(ctx, dep.stage, dep.unit_id, suffix="manifest.json")
            tables.extend(receipt["tables"])
        elif action == "quality":
            report = io.receipt(ctx, dep.stage, dep.unit_id, suffix=".json")
            reports.append(report)
            named.extend(report["named"])
        elif action == "places":
            for kind in ("places", "canonical_cities", "place_to_city"):
                tables.append(io.table(ctx, dep.stage, dep.unit_id, kind, country=key))
        elif action == "block":
            tables.append(io.table(ctx, dep.stage, dep.unit_id, "cells", block=key))
        elif action == "names":
            tables.append(io.table(ctx, dep.stage, dep.unit_id, "names"))
        elif action in {"static", "spatial"}:
            kind = key.partition("/")[0]
            tables.append(io.table(ctx, dep.stage, dep.unit_id, kind))
        else:
            raise ValueError(f"Unexpected lookup manifest input: {dep.key}")
    local_tables = io.local(ctx, tables)
    root.mkdir(parents=True, exist_ok=True)
    integrity = measure(
        root,
        local_tables,
        [t for t in local_tables if t["kind"] == "cells"],
        ctx.config.resources,
        ctx.config.engines.limits,
        grid=ctx.config.h3,
    )
    references = reference_checks(local_tables, ctx.config.resources)
    references["dangling_names"] = names.dangling(
        local_tables, root / "spill", ctx.config.resources, ctx.config.engines.limits
    )
    approval = reviews.load(located(REPOSITORY, ctx.config.engines.city_review), policy)
    failed = failures(reports, named)
    losses = failed["all_boundaries"]
    exceptions = [asdict(item) for item in approval.boundary_exceptions]
    origins = resolver(
        lambda cc: io.artifact(ctx, "reconcile", "country/" + cc, suffix=".sqlite"),
        ctx.config.engines.limits.sqlite_cache_kib,
    )
    failed["all_boundaries"] = unreviewed(losses, exceptions, origins)
    rows: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    for table in tables:
        rows[table["kind"]] += table["rows"]
        sizes[table["kind"]] += table["size"]
    quality = root / "quality.json"
    write_json(
        quality,
        {
            "rows": dict(rows),
            "bytes": dict(sizes),
            "integrity": integrity,
            "normalization_integrity": references,
            "named": named,
            "failed_spatial_gates": failed,
            "boundary_losses": losses,
            "boundary_exceptions": exceptions,
        },
    )
    errors = {
        key: value
        for key, value in integrity.items()
        if key != "represented_r8_centres" and value
    }
    if errors or any(references.values()) or any(failed.values()):
        raise ValueError(
            f"Stored dataset gate failed; inspect {quality.relative_to(ctx.root)}"
        )
    manifest = root / "manifest.json"
    write_json(
        manifest,
        {
            "schema_version": "cells",
            "completed": True,
            "normalization": {"completed": True, "policy": policy},
            "reference_resolution": ctx.config.h3.cell_resolution,
            "block_resolution": ctx.config.h3.block_resolution,
            "tables": tables,
            "policy": policy,
            "verification_artifacts": [file_record(ctx.root, quality)],
        },
    )
    pointer = located(ctx.root, ctx.config.paths.cells) / "current.json"
    write_json(pointer, {"manifest": file_record(ctx.root, manifest)})
    return [quality, manifest, pointer]
