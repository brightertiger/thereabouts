"""A planning unit republishes its inventory before dependent work is discovered."""

from dataclasses import replace
from pathlib import Path

from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.runtime.runner import run
from pipeline.stages.contract import Context, Unit, make_unit

from .helpers import SyntheticStage, context


class InventoryStage(SyntheticStage):
    def units(self, ctx: Context) -> list[Unit]:
        initial = make_unit(
            ctx,
            Recipe(self.name, "inventory", {"contents": self.content}),
            self.identity(ctx),
        )
        units = [replace(initial, refresh_discovery=True)]
        path = ctx.root / "inventory.json"
        if path.exists():
            import json

            for key in json.loads(path.read_text())["keys"]:
                units.append(make_unit(ctx, Recipe(self.name, key), self.identity(ctx)))
        return units

    def run(self, ctx: Context, unit: Unit) -> list[Path]:
        if unit.recipe.unit_id == "inventory":
            output = ctx.root / "inventory.json"
            write_json(output, {"keys": self.content.split(",")})
            self.calls.append("inventory")
            return [output]
        return super().run(ctx, unit)


def test_inventory_refresh_adds_units_in_same_command(tmp_path: Path) -> None:
    stage = InventoryStage("items", [], content="one")
    with Ledger(
        tmp_path, tmp_path / "ledger.sqlite3", readonly=False, timeout=30
    ) as ledger:
        ctx = context(tmp_path, ledger)
        assert run(ctx, [stage])["completed"] == 2
        assert stage.calls == ["inventory", "one"]
        assert run(ctx, [stage])["completed"] == 0
        stage.content = "one,two"
        assert run(ctx, [stage])["completed"] == 2
        assert stage.calls[-2:] == ["inventory", "two"]
        assert ledger.get("items", "two") is not None
