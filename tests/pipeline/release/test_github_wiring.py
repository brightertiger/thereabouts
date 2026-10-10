"""`release upload` and the publish stage send a proven release to GitHub."""

import json
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.release_command import main
from pipeline.runtime.context import context
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.stages.publish import PublishStage
from tests.tools.github_fake import FakeGithub, running

from .github_release import Built, build


def arguments(built: Built, fake: FakeGithub) -> list[str]:
    return [
        "upload",
        "--root",
        str(built.root),
        "--version",
        built.version,
        "release.packs.families=[core,phone]",
        "release.publish.target=github",
        *fake.overrides(),
    ]


def prove(built: Built) -> None:
    """Ledger records for exactly the files the upload will publish."""
    root, version = built.root, built.version
    packs = root / "packs" / version
    records = {
        ("dataset", version): [built.dataset / "manifest.json"],
        **{
            ("packs", f"{version}/{family}"): [
                packs / f"{family}.tar.zst",
                packs / "acceptance" / f"{family}.json",
            ]
            for family in built.packs
        },
        ("packs", f"{version}/index"): [packs / "index.json"],
    }
    with Ledger(
        root, root / "work/ledger.sqlite3", readonly=False, timeout=30
    ) as ledger:
        for (stage, unit), paths in records.items():
            ledger.register(Recipe(stage, unit))
            ledger.complete(stage, unit, "0" * 64, paths)


def test_upload_needs_proof_before_any_request(tmp_path: Path) -> None:
    built = build(tmp_path)
    with running() as fake:
        with pytest.raises(ValueError, match="no pipeline ledger"):
            main([*arguments(built, fake), "--dry-run"])
        assert fake.requests == []


def test_upload_plans_offline_then_publishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    built = build(tmp_path)
    prove(built)
    with running(FakeGithub(private=False)) as fake:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert main([*arguments(built, fake), "--dry-run"]) == 0
        planned = json.loads(capsys.readouterr().out)
        assert (planned["dry_run"], planned["tag"]) == (True, "v2026.10")
        assert fake.requests == []
        monkeypatch.setenv("GITHUB_TOKEN", fake.token)
        assert main(arguments(built, fake)) == 0
        published = json.loads(capsys.readouterr().out)
        assert published["state"] == "published"
        assert fake.published("v2026.10") is not None


def test_the_publish_stage_dispatches_to_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build(tmp_path)
    with running() as fake:
        config = load(
            overrides=[
                f"paths.root={tmp_path}",
                "release.enabled=true",
                'release.version="2026.10"',
                "release.packs.families=[core,phone]",
                "release.publish.target=github",
                *fake.overrides(),
            ]
        )
        stage = PublishStage(next(s for s in config.stages if s.name == "publish"))
        with Ledger(
            tmp_path, tmp_path / "work/ledger.sqlite3", readonly=False, timeout=30
        ) as ledger:
            ctx = context(config, tmp_path, ledger)
            ctx.readonly = False
            (unit,) = stage.units(ctx)
            parameters = unit.recipe.parameters
            assert parameters["destination"] == "github:brightertiger/thereabouts"
            monkeypatch.setenv("GITHUB_TOKEN", fake.token)
            (receipt,) = stage.run(ctx, unit)
        assert json.loads(receipt.read_text())["state"] == "published"
        assert receipt == tmp_path / "work/releases/2026.10/publish.json"
        assert fake.published("v2026.10") is not None
