"""Executable synthetic stages and legacy evidence, with no external inputs."""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pipeline.config import load
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
from pipeline.stages.contract import Context, Unit, make_unit


def context(root: Path, ledger: Ledger) -> Context:
    config = load(overrides=["resources.workers=2"])
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


def legacy_workspace(root: Path) -> Path:
    raw = root / "raw/ghsl/input.zip"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"synthetic archive")
    inventory = raw.parent / "inventory.json"
    write_json(inventory, {"source": "ghsl", "files": {"input": record(raw)}})
    part = root / "normalized/ghsl/areas/part.parquet"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"synthetic parquet bytes")
    manifest = part.parent.parent / "manifest.json"
    write_json(
        manifest,
        {
            "source": "ghsl",
            "source_release": "fixture",
            "inventory": record(inventory),
            "auxiliary": [],
            "inputs": [record(raw)],
            "partitions": [record(part)],
            "units": [
                {
                    "stage": "ghsl.normalize",
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
                    f"ghsl.{stage}",
                    key,
                    "old-inputs",
                    json.dumps([record(output)]),
                    "{}",
                    "2026-10-03T00:00:00+00:00",
                ),
            )
    return path
