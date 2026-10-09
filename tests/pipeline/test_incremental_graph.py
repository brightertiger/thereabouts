"""Production stages rebuild only what an edit actually reaches."""

import shutil
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.runtime.execution import Executor
from pipeline.runtime.fingerprints import REPOSITORY, stage_identity
from pipeline.runtime.jsonio import digest
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.records import Dependency, Recipe
from pipeline.runtime.runner import run
from pipeline.stages import geographic
from pipeline.stages.contract import Context, Stage
from thereabouts.format import CELL_FORMAT_VERSION

from .geographic_fixtures import geographic_graph, source_receipts
from .helpers import SyntheticStage
from .sources.fixtures import source_context
from .test_recorded_content import boundary_payloads

GEOGRAPHIC = ("reconcile", "cells", "cities", "normalize_cells")


def execute(ctx: Context, stages: list[Stage]) -> set[tuple[str, str]]:
    executor = Executor(ctx, stages, lambda _: None)
    executor.execute("lookups")
    return executor.completed_keys


def test_release_settings_edit_reidentifies_release_stages_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    shutil.copytree(
        REPOSITORY / "pipeline",
        repository / "pipeline",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(REPOSITORY / "uv.lock", repository / "uv.lock")
    monkeypatch.setattr(
        geographic, "stage_identity", partial(stage_identity, repository=repository)
    )
    config = load()

    def identities() -> dict[str, str]:
        return {
            stage.name: stage_identity(
                stage,
                config,
                cell_format=CELL_FORMAT_VERSION,
                repository=repository,
            )
            for stage in config.stages
        }

    with Ledger(tmp_path / "workspace", None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path / "workspace", ledger)
        assert execute(ctx, geographic_graph(ctx, normalized))
        before = identities()
        release = repository / "pipeline/config/release.py"
        release.write_text(release.read_text().replace('"""', '"""Edited. ', 1))
        after = identities()
        assert {name for name in before if before[name] != after[name]} == {
            "dataset",
            "packs",
            "publish",
        }
        assert execute(ctx, geographic_graph(ctx, normalized)) == set()


def test_transfer_settings_change_reruns_nothing(tmp_path: Path) -> None:
    reader = SyntheticStage(
        "reader",
        [
            Recipe(
                "reader",
                "areas",
                dependencies=(
                    Dependency(
                        "normalize",
                        "geoboundaries",
                        ("normalized/geoboundaries/areas/*.parquet",),
                    ),
                ),
            )
        ],
        needs=("normalize",),
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        runtime, source, stages = source_context(
            tmp_path, ledger, "geoboundaries", boundary_payloads(tmp_path)
        )
        source.pin.metadata["country_reference"] = {"GBR": {"alpha2": "GB"}}
        graph: list[Stage] = [*stages, reader]
        assert run(runtime, graph) == {"completed": 3, "skipped": 0}
        settings = runtime.config.sources["geoboundaries"]
        settings.limits = replace(settings.limits, retries=9, timeout_seconds=120.0)
        settings.upstream = {**settings.upstream, "url": "https://mirror.example/x"}
        assert all(item.state == "current" for item in plan(runtime, graph))
        assert run(runtime, graph) == {"completed": 0, "skipped": 3}


@pytest.mark.parametrize("changed", GEOGRAPHIC)
def test_identity_only_change_reruns_that_stage_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path, ledger)
        built = execute(ctx, geographic_graph(ctx, normalized))
        original = geographic.GeographicStage.identity

        def cosmetic(self: geographic.GeographicStage, ctx: Context) -> str:
            value = original(self, ctx)
            return digest([value, "cosmetic"]) if self.name == changed else value

        monkeypatch.setattr(geographic.GeographicStage, "identity", cosmetic)
        rebuilt = execute(ctx, geographic_graph(ctx, normalized))
        assert rebuilt and rebuilt == {key for key in built if key[0] == changed}
