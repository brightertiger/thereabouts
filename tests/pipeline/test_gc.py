"""gc removes superseded outputs and crash leftovers, never referenced files."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from pipeline.cli import main
from pipeline.config import load
from pipeline.runtime.gc import garbage
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency, Recipe
from pipeline.runtime.runner import exclusive, run
from pipeline.stages.contract import Context, Unit

from .helpers import HashedStage, SyntheticStage, context

HEX = "c" * 64


@dataclass
class ManifestStage(SyntheticStage):
    """Lists the upstream table by path, as production manifests do."""

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        self.calls.append(unit.recipe.unit_id)
        record = ctx.ledger.get("first", "one")
        assert record is not None
        [table] = [o for o in record.outputs if not o.path.endswith(".json")]
        path = ctx.root / self.name / unit.inputs_hash / "manifest.json"
        write_json(path, {"table": {"path": table.path, "sha256": table.sha256}})
        return [path]


def leftovers(root: Path, live: Path) -> list[Path]:
    paths = [
        live / "x.part",
        root / "packs/2026.10/.core.building/shard",
        live / "spill/duckdb_temp_storage-0.tmp",
        root / f"raw/src/sha256/{HEX}.part",
        root / f"raw/src/{HEX}/kept",
    ]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("leftover")
    return paths


def test_gc_keeps_what_records_and_their_manifests_reference(tmp_path: Path) -> None:
    first = HashedStage("first", [Recipe("first", "one")])
    second = ManifestStage(
        "second",
        [
            Recipe(
                "second",
                "one",
                dependencies=(Dependency("first", "one", paths=("first/one",)),),
            )
        ],
        needs=("first",),
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        directories = []
        for implementation in ("a", "b", "c"):
            first.implementation = implementation
            run(ctx, [first, second])
            record = ledger.get("first", "one")
            assert record is not None
            directories.append(tmp_path / Path(record.outputs[0].path).parent)
        assert second.calls == ["one"]
        listed, superseded, current = directories
        part, building, spill, raw_part, raw_kept = leftovers(tmp_path, current)
        found = garbage(tmp_path, ctx.config, ledger)
        assert set(found) == {superseded, part, building.parent, spill.parent}
        # The first copy is still named by the skipped consumer's manifest.
        assert listed.is_dir() and current.is_dir()
        assert not {raw_part, raw_kept.parent} & set(found)
        assert all(path.exists() for path in found)


def workspace(root: Path) -> Path:
    with Ledger(
        root,
        root / "work/ledger.sqlite3",
        readonly=False,
        timeout=load().resources.ledger_timeout_seconds,
    ):
        pass
    orphan = root / "normalized/src/areas" / HEX / "part.parquet"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("superseded")
    return orphan.parent


def test_gc_command_dry_run_lock_and_removal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "workspace"
    orphan = workspace(root)
    assert main(["gc", "--dry-run", "--root", str(root)]) == 0
    assert orphan.exists() and "would remove" in capsys.readouterr().out
    with exclusive(root / "work/pipeline.lock"):
        assert main(["gc", "--root", str(root)]) == 2
    assert "Another pipeline writer" in capsys.readouterr().out
    assert orphan.exists()
    assert main(["gc", "--root", str(root)]) == 0
    assert not orphan.exists()
    assert (root / "work/ledger.sqlite3").exists()
