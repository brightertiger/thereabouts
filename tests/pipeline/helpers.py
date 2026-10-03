"""Executable synthetic stages and legacy evidence, with no external inputs."""

import json
import resource
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from pipeline.config import Config, load
from pipeline.config.loader import CONFIG_DIR
from pipeline.config.schema import Resources
from pipeline.runtime.jsonio import (
    Object,
    atomic_output,
    digest,
    sha256_file,
    write_json,
)
from pipeline.runtime.ledger import UNITS_SQL, Ledger
from pipeline.runtime.records import Recipe
from pipeline.runtime.resources import ResourceGuard
from pipeline.runtime.verification import Verifier
from pipeline.stages.contract import Context, Stage, Unit, make_unit
from pipeline.stages.retained import RetainedStage


def peak_rss() -> int:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage if sys.platform == "darwin" else usage * 1024)


def context(root: Path, ledger: Ledger) -> Context:
    config = Config(resources=Resources(workers=2))
    guard = ResourceGuard(
        root,
        config.resources,
        free=lambda _: 10_000_000_000,
        used=lambda _: 0,
        rss=lambda: 0,
    )
    return Context(config, root, ledger, guard, Verifier(root), readonly=False)


@dataclass
class SyntheticStage:
    name: str
    recipes: list[Recipe]
    needs: tuple[str, ...] = ()
    content: str = "unchanged"
    implementation: str = "initial"
    calls: list[str] = field(default_factory=list)
    fail: bool = False
    discover_after: str | None = None

    def identity(self, ctx: Context) -> str:
        return digest({"implementation": self.implementation})

    def units(self, ctx: Context) -> list[Unit]:
        if self.discover_after and not (ctx.root / self.discover_after).exists():
            return []
        return [make_unit(ctx, recipe, self.identity(ctx)) for recipe in self.recipes]

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        self.calls.append(unit.recipe.unit_id)
        for dependency in unit.recipe.dependencies:
            assert ctx.ledger.get(*dependency.key) is not None
        path = ctx.root / self.name / unit.recipe.unit_id
        with atomic_output(path) as temporary:
            temporary.write_text(self.content)
            if self.fail:
                raise ValueError("synthetic interruption")
        return [path]

    def finish(self, ctx: Context) -> None:
        write_json(ctx.root / f"{self.name}.json", {"complete": True})


def record(path: Path) -> Object:
    name = str(path.absolute())
    return {"path": name, "size": path.stat().st_size, "sha256": sha256_file(path)}


def legacy_workspace(root: Path, *, source: str = "ghsl") -> Path:
    raw = root / f"raw/{source}/input.zip"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"synthetic archive")
    inventory = raw.parent / "inventory.json"
    write_json(inventory, {"source": source, "files": {"input": record(raw)}})
    part = root / f"normalized/{source}/areas/part.parquet"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"synthetic parquet bytes")
    manifest = part.parent.parent / "manifest.json"
    write_json(
        manifest,
        {
            "source": source,
            "source_release": "fixture",
            "inventory": record(inventory),
            "auxiliary": [],
            "inputs": [record(raw)],
            "partitions": [record(part)],
            "units": [
                {
                    "stage": f"{source}.normalize",
                    "unit_id": "world",
                    "inputs_hash": "old-inputs",
                }
            ],
        },
    )
    path = root / "work/ledger.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path) as db:
        db.execute(UNITS_SQL)
        for stage, key, output in [
            ("download", "input", raw),
            ("normalize", "world", part),
            ("manifest", "current", manifest),
        ]:
            db.execute(
                "INSERT INTO units VALUES (?,?,?,?,?,?)",
                (
                    f"{source}.{stage}",
                    key,
                    "old-inputs",
                    json.dumps([record(output)]),
                    "{}",
                    "2026-10-03T00:00:00+00:00",
                ),
            )
    return path


def retained_stages() -> list[Stage]:
    """The frozen stand-ins used by the initial legacy migration."""
    return [
        RetainedStage(settings)
        for settings in load(CONFIG_DIR / "adoption.yaml").stages
    ]


def source_options(root: Path) -> list[str]:
    """A one-source configuration for independent CLI discovery over tiny evidence."""
    config = load()
    config.sources = {"ghsl": config.sources["ghsl"]}
    config.stages = [
        stage for stage in config.stages if stage.name in {"download", "normalize"}
    ]
    path = root.parent / "pipeline.yaml"
    path.write_text(yaml.safe_dump(asdict(config), sort_keys=False))
    return ["--config", str(path)]
