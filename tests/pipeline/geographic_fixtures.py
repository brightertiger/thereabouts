"""Complete tiny source receipts for exercising the real geographic runner."""

from pathlib import Path

import h3
import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.config import load
from pipeline.engines.artifact_io import file_record
from pipeline.runtime.execution import Executor
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.sources.shared.schemas import SCHEMAS
from pipeline.stages.contract import Context, Stage, make_unit
from pipeline.stages.registry import ordered, registry
from tests.pipeline.reconciliation.conftest import area, place, write_inputs

from .helpers import SyntheticStage, context


def source_receipts(root: Path, ledger: Ledger) -> tuple[Context, SyntheticStage]:
    config = load()
    config.engines.countries = ["ZZ"]
    config.engines.blocks = [h3.latlng_to_cell(0, 0, 3)]
    config.resources.workers = 1
    config.resources.duckdb_memory = "128MB"
    ctx = context(root, ledger)
    ctx.config = config
    extracted = write_inputs(
        root / "normalized" / "fixture",
        geonames=[place("1", "Town", 0, 0, population=50000)],
        divisions=[place("town", "Town", 0, 0, source="overture")],
        areas=[
            area("nation", "Nation", "country", (-5, -5, 5, 5)),
            area("town", "Town", "locality", (-0.1, -0.1, 0.1, 0.1)),
        ],
    )
    source_names = ["overture", "geonames", "geoboundaries", "osm_land", "ghsl"]
    stage = SyntheticStage(
        "normalize", [Recipe("normalize", name) for name in source_names]
    )
    for recipe in stage.recipes:
        source = recipe.unit_id
        parts, paths = [], []
        if source in {"osm_land", "ghsl"}:
            path = root / "normalized" / source / "areas.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            rows = (
                [area("physical", "Land", "land", (-5, -5, 5, 5), source=source)]
                if source == "osm_land"
                else []
            )
            pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMAS["areas"]), path)
            paths.append(path)
            parts.append(
                {**file_record(root, path), "kind": "areas", "rows": len(rows)}
            )
        else:
            for kind in config.engines.reconcile_sources[source]:
                path = extracted / f"{source}_{kind}.parquet"
                paths.append(path)
                parts.append(
                    {
                        **file_record(root, path),
                        "kind": kind,
                        "rows": pq.read_metadata(path).num_rows,
                    }
                )
        manifest = root / "normalized" / source / "manifest.json"
        write_json(manifest, {"source": source, "partitions": parts})
        unit = make_unit(ctx, recipe, stage.identity(ctx))
        ledger.register(recipe)
        ledger.complete(
            *recipe.key,
            unit.inputs_hash,
            [manifest, *paths],
            metadata={
                "identity": unit.identity,
                "dependency_hash": unit.dependency_hash,
            },
        )
    return ctx, stage


GEOGRAPHIC = ("reconcile", "cells", "cities", "normalize_cells", "lookups")


def geographic_graph(ctx: Context, normalized: SyntheticStage) -> list[Stage]:
    """The production geographic stages, with a passing synthetic review gate."""
    review = SyntheticStage(
        "evaluate", [Recipe("evaluate", "pilot")], needs=("cells", "cities")
    )
    production = [
        stage
        for stage in registry(ctx.config)
        if stage.name in {*GEOGRAPHIC, "plate_country"}
    ]
    return ordered([normalized, review, *production])


def build(ctx: Context, stages: list[Stage], target: str = "lookups") -> dict[str, int]:
    """Run what the target needs; the fixture's reconcile pilot gate cannot pass."""
    executor = Executor(ctx, stages, lambda _: None)
    executor.execute(target)
    return {"completed": executor.completed, "skipped": executor.skipped}
