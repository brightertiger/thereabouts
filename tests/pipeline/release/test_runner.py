"""Exercise the release stages through the runner and a persistent synthetic ledger."""

import json
from dataclasses import asdict
from pathlib import Path

import fsspec
import pytest

from pipeline.engines.artifact_io import file_record
from pipeline.pins.models import PinFile, SourcePin
from pipeline.release import acceptance, client, metadata, pins
from pipeline.release.source import Row
from pipeline.runtime.context import context
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.planning import plan
from pipeline.runtime.records import Recipe
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context, Stage, Unit
from pipeline.stages.dataset import DatasetStage
from pipeline.stages.packs import PacksStage
from pipeline.stages.publish import PublishStage

from ..helpers import SyntheticStage
from .fixtures import fixture


class Lookups(SyntheticStage):
    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        self.calls.append(unit.recipe.unit_id)
        return [ctx.root / "manifest.json", *sorted(ctx.root.glob("*.parquet"))]


def source_evidence(root: Path) -> SourcePin:
    raw = root / "raw/timezones/input"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"synthetic timezone input")
    record = file_record(root, raw)
    pin = SourcePin(
        "fixture",
        "2026-10-03",
        files=[
            PinFile(
                "input",
                "http://localhost/input",
                record["size"],
                record["sha256"],
                metadata={"license": "Public-Domain", "attribution": "Fixture author"},
            )
        ],
    )
    inventory = raw.parent / "inventory.json"
    write_json(
        inventory,
        {
            "source_release": pin.release,
            "pinned_at": pin.pinned_at,
            "pin_metadata": pin.metadata,
            "files": {"input": {**asdict(pin.files[0]), "path": record["path"]}},
        },
    )
    write_json(
        root / "normalized/timezones/manifest.json",
        {
            "source": "timezones",
            "inventory": file_record(root, inventory),
            "inputs": [record],
        },
    )
    return pin


def test_release_through_publish_commits_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot, config, _ = fixture(tmp_path)
    root = snapshot.root
    config.sources = {"timezones": config.sources["timezones"]}
    config.release.packs.families = ["core", "postal"]
    config.storage["s3_release"] = f"memory://release-runner/{tmp_path.name}"
    pin = source_evidence(root)
    monkeypatch.setattr(metadata, "read_lock", lambda path: {"timezones": pin})
    monkeypatch.setattr(pins, "read_lock", lambda path: {"timezones": pin})
    fs, base = fsspec.core.url_to_fs(config.storage["s3_release"])
    marker = f"{base}/dataset/2026.10/_SUCCESS"
    calls = []

    def writer(directory: str, family: str, target: str, options: Row) -> Row:
        assert not fs.exists(marker)
        assert (Path(directory) / "manifest.json").is_file()
        assert options["data_version"] == "2026.10"
        calls.append(family)
        destination = Path(target)
        destination.mkdir(parents=True)
        payload = destination / "client-owned.bin"
        payload.write_text(f"synthetic client pack {family}")
        result = {"format_minor": 2, "files": [file_record(destination, payload)]}
        write_json(destination / "manifest.json", result)
        return result

    monkeypatch.setattr(client, "binding", lambda: writer)

    def accepted(dataset: Path, packs: Path, family: str, *args: object) -> Path:
        # The synthetic client output is not a pack; acceptance has its own tests.
        report = packs / "acceptance" / f"{family}.json"
        write_json(report, {"family": family, "passed": True})
        return report

    monkeypatch.setattr(acceptance, "accept", accepted)
    settings = {stage.name: stage for stage in config.stages}
    lookups = Lookups("lookups", [Recipe("lookups", "manifest/current")])
    stages: list[Stage] = [
        lookups,
        DatasetStage(settings["dataset"]),
        PacksStage(settings["packs"]),
        PublishStage(settings["publish"]),
    ]
    with Ledger(
        root,
        root / "work/ledger.sqlite3",
        readonly=False,
        timeout=config.resources.ledger_timeout_seconds,
    ) as ledger:
        ctx = context(config, root, ledger)
        ctx.readonly = False
        assert run(ctx, stages, through="publish") == {"completed": 6, "skipped": 0}
        receipt = json.loads(fs.cat(marker))
        assert receipt["version"] == "2026.10"
        paths = {entry["path"] for entry in receipt["files"]}
        assert {
            "dataset/2026.10/manifest.json",
            "dataset/2026.10/data_dictionary.json",
            "packs/2026.10/core.tar.zst",
            "packs/2026.10/postal.tar.zst",
            "packs/2026.10/acceptance/core.json",
            "packs/2026.10/acceptance/postal.json",
            "packs/2026.10/index.json",
        } <= paths
        # Archives only: no loose pack artifact is published.
        assert not [
            p
            for p in paths
            if p.startswith(("packs/2026.10/core/", "packs/2026.10/postal/"))
        ]
        assert fs.cat(f"{base}/packs/2026.10/_SUCCESS") == fs.cat(marker)
        assert not fs.exists(f"{base}/2026.10/_SUCCESS")
        aggregate = json.loads(fs.cat(f"{base}/packs/index.json"))
        assert aggregate["datasets"]["2026.10"]["packs"]["core"]["url"] == (
            "2026.10/core.tar.zst"
        )
        local = json.loads((root / "work/releases/2026.10/publish.json").read_text())
        assert local["files"] == receipt["files"]
        assert all(decision.state == "current" for decision in plan(ctx, stages))
        assert run(ctx, stages, through="publish") == {"completed": 0, "skipped": 6}
        assert sorted(calls) == ["core", "postal"]
        assert lookups.calls == ["manifest/current"]
        assert len(ledger.recipes()) == 6
    fs.rm(base, recursive=True)
