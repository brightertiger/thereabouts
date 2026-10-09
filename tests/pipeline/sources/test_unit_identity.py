"""A source pin or adapter edit invalidates that source and its readers only."""

from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.config.schema import StageSettings
from pipeline.config.sources import SourceSettings
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.records import Dependency, Recipe
from pipeline.stages import sources
from pipeline.stages.contract import Stage
from pipeline.stages.registry import registry

from ..helpers import SyntheticStage, context


def test_source_changes_do_not_invalidate_unrelated_units(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    for name in ("shared", "alpha", "beta"):
        path = repository / f"pipeline/sources/{name}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n")
    (repository / "uv.lock").write_text("package = []\n")
    monkeypatch.setattr(sources, "REPOSITORY", repository)
    settings = {
        name: SourceSettings(name=name, adapter=f"pipeline.sources.{name}")
        for name in ("alpha", "beta")
    }
    pins = {
        name: SourcePin(
            "initial",
            "2026-10-03",
            files=[PinFile("input", f"memory://{name}", 1, "a" * 64)],
        )
        for name in settings
    }
    stages: list[Stage] = [
        sources.SourceStage(
            StageSettings(
                name=name,
                packages=["pipeline/sources/shared.py"],
                needs=["download"] if name == "normalize" else [],
            ),
            pins,
        )
        for name in ("download", "normalize")
    ]
    stages.append(
        SyntheticStage(
            "reader",
            [
                Recipe("reader", name, dependencies=(Dependency("normalize", name),))
                for name in settings
            ],
            needs=("normalize",),
        )
    )
    root = tmp_path / "workspace"
    with Ledger(root, None, readonly=False) as ledger:
        ctx = context(root, ledger)
        ctx.config.sources = settings
        for stage in stages:
            for unit in stage.units(ctx):
                output = root / unit.recipe.stage / unit.recipe.unit_id
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("retained")
                ledger.register(unit.recipe)
                ledger.complete(
                    *unit.key,
                    unit.inputs_hash,
                    [output],
                    metadata={
                        "identity": unit.identity,
                        "dependency_hash": unit.dependency_hash,
                    },
                )
        assert all(item.state == "current" for item in plan(ctx, stages))

        def changed() -> set[tuple[str, str]]:
            return {
                (d.stage, d.unit_id) for d in plan(ctx, stages) if d.state != "current"
            }

        expected = {(name, "alpha") for name in ("download", "normalize", "reader")}
        pins["alpha"].release = "next"
        assert changed() == expected
        pins["alpha"].release = "initial"
        # Downloads fetch the pin; only normalizers run the adapter.
        (repository / "pipeline/sources/alpha.py").write_text("value = 2\n")
        assert changed() == expected - {("download", "alpha")}


def source_hashes(tmp_path: Path, *overrides: str) -> dict[tuple[str, str], str]:
    config = load(overrides=overrides)
    stages = [s for s in registry(config) if s.name in {"download", "normalize"}]
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        ctx.config = config
        return {
            unit.key: unit.inputs_hash for stage in stages for unit in stage.units(ctx)
        }


@pytest.mark.parametrize(
    "edit",
    [
        "limits.retries=9",
        "limits.timeout_seconds=120",
        "limits.backoff_seconds=3",
        "limits.download_bytes=1",
        "upstream.url=https://mirror.example/allCountries.zip",
    ],
)
def test_transfer_settings_change_no_unit(tmp_path: Path, edit: str) -> None:
    base = source_hashes(tmp_path)
    assert len(base) > 20
    assert source_hashes(tmp_path, f"sources.geonames.{edit}") == base


def test_normalize_settings_change_that_normalizer_only(tmp_path: Path) -> None:
    base = source_hashes(tmp_path)
    edited = source_hashes(tmp_path, "sources.geonames.limits.batch_rows=8")
    assert {key for key in base if base[key] != edited[key]} == {
        ("normalize", "geonames")
    }
