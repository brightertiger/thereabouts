"""Data files a unit reads at run time are part of that unit's identity."""

import shutil
import sys
import threading
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

from pipeline.runtime.fingerprints import REPOSITORY, native_versions
from pipeline.runtime.ledger import Ledger
from pipeline.stages import parameters
from pipeline.stages.contract import Context, Stage, Unit
from pipeline.stages.registry import registry

from .geographic_fixtures import build, geographic_graph, source_receipts

EVIDENCE = (REPOSITORY / "eval", REPOSITORY / "config/reviews")
CURRENT = threading.local()
OPENED: dict[tuple[str, str], set[str]] = defaultdict(set)


def audit(event: str, args: tuple[Any, ...]) -> None:
    key = getattr(CURRENT, "key", None)
    if event != "open" or key is None or not isinstance(args[0], (str, Path)):
        return
    path = Path(args[0]).absolute()
    if any(path.is_relative_to(root) for root in EVIDENCE):
        OPENED[key].add(path.relative_to(REPOSITORY).as_posix())


sys.addaudithook(audit)


def observed(stage: Stage) -> Callable[[Context, Unit], list[Path]]:
    run = stage.run

    def wrapped(ctx: Context, unit: Unit) -> list[Path]:
        CURRENT.key = unit.key
        try:
            return run(ctx, unit)
        finally:
            CURRENT.key = None

    return wrapped


def test_every_evaluation_file_a_unit_opens_is_hashed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    OPENED.clear()
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path, ledger)
        stages = geographic_graph(ctx, normalized)
        for stage in stages:
            monkeypatch.setattr(stage, "run", observed(stage))
        build(ctx, stages)
        assert OPENED, "the synthetic graph opens evaluation fixtures"
        for (name, unit_id), paths in OPENED.items():
            recipe = ledger.recipe(name, unit_id)
            assert recipe is not None
            reads = cast(dict[str, str], recipe.parameters.get("reads", {}))
            assert paths <= set(reads), (name, unit_id, paths - set(reads))


def unit_hashes(tmp_path: Path, repository: Path) -> dict[tuple[str, str], str]:
    with Ledger(tmp_path / "workspace", None, readonly=False) as ledger:
        ctx, _ = source_receipts(tmp_path / "workspace", ledger)
        result: dict[tuple[str, str], str] = {}
        for stage in registry(ctx.config):
            if stage.name in {"download", "normalize", "dataset", "packs", "publish"}:
                continue
            result |= {unit.key: unit.inputs_hash for unit in stage.units(ctx)}
        return result


@pytest.mark.parametrize(
    ("name", "readers"),
    [
        (
            "eval/cities/probes.json",
            {("evaluate", "pilot"), ("normalize_cells", "quality/ZZ")},
        ),
        (
            "config/reviews/cities-pilot.yaml",
            {("evaluate", "pilot"), ("lookups", "manifest/current")},
        ),
        (
            "eval/reconcile/fixtures.json",
            {
                ("evaluate", "pilot"),
                ("normalize_cells", "quality/ZZ"),
                ("reconcile", "gate/pilot"),
            },
        ),
    ],
)
def test_an_edited_data_file_re_identifies_its_readers_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    readers: set[tuple[str, str]],
) -> None:
    repository = tmp_path / "repository"
    for directory in ("config", "eval"):
        shutil.copytree(REPOSITORY / directory, repository / directory)
    monkeypatch.setattr(parameters, "REPOSITORY", repository)
    before = unit_hashes(tmp_path / "before", repository)
    with (repository / name).open("a") as stream:
        stream.write("\n")
    after = unit_hashes(tmp_path / "after", repository)
    assert {key for key in before if before[key] != after[key]} == readers


def test_pack_identity_follows_writer_revisions() -> None:
    from thereabouts import _core

    revisions = native_versions(["thereabouts"], REPOSITORY / "uv.lock")
    writer = revisions["thereabouts_writer"]
    assert vars(_core)["CORE_REVISION"] in writer
    assert vars(_core)["WRITER_REVISION"] in writer
