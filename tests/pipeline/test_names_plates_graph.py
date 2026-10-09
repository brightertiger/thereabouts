"""The production graph publishes names and the writer's plate tables as lookups."""

import json
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.paths import located
from pipeline.runtime.records import Recipe
from pipeline.stages.contract import Context, make_unit
from pipeline.stages.engine_discovery import Discovery

from .geographic_fixtures import build, geographic_graph, source_receipts
from .helpers import SyntheticStage
from .test_names import alias
from .test_plate_tables import workspace

PLATES = {"plate_formats", "plate_codes", "plate_policy", "plate_priors"}


def plates_receipt(ctx: Context, normalized: SyntheticStage, ledger: Ledger) -> None:
    """A normalized `plates` source: inventory, pinned documents and one code."""
    manifest = workspace(ctx.root)
    path = ctx.root / "normalized/plates/manifest.json"
    write_json(path, manifest)
    recipe = Recipe("normalize", "plates")
    normalized.recipes.append(recipe)
    unit = make_unit(ctx, recipe, normalized.identity(ctx))
    ledger.register(recipe)
    ledger.complete(
        *recipe.key,
        unit.inputs_hash,
        [path, *(ctx.root / p["path"] for p in manifest["partitions"])],
        metadata={"identity": unit.identity, "dependency_hash": unit.dependency_hash},
    )


def test_recipes_declare_name_and_plate_reads(tmp_path: Path) -> None:
    with Ledger(tmp_path / "workspace", None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path / "workspace", ledger)
        plates_receipt(ctx, normalized, ledger)
        discovery = Discovery()
        discovery.load(ctx)
        (names,) = [
            r for r in discovery.recipes["lookups"] if r.unit_id == "names/world"
        ]
        reads = {d.unit_id: d.paths for d in names.dependencies if d.paths}
        # The fixture's Overture source publishes no names partition.
        assert reads == {
            "geonames": (
                "normalized/geonames/names/*.parquet",
                "normalized/geonames/places/*.parquet",
            )
        }
        assert ("normalize_cells", "places/ZZ") in {d.key for d in names.dependencies}
        (plates,) = discovery.recipes["plate_country"]
        (dependency,) = plates.dependencies
        assert dependency.key == ("normalize", "plates")
        assert "normalized/plates/manifest.json" in dependency.paths
        (manifest,) = [
            r for r in discovery.recipes["lookups"] if r.unit_id == "manifest/current"
        ]
        assert {("plate_country", "world"), ("lookups", "names/world")} <= {
            d.key for d in manifest.dependencies
        }


def test_graph_publishes_names_and_plate_tables(tmp_path: Path) -> None:
    town = [alias("900", "1", "Stadt", language="de")]
    with Ledger(tmp_path / "workspace", None, readonly=False) as ledger:
        ctx, normalized = source_receipts(tmp_path / "workspace", ledger, names=town)
        plates_receipt(ctx, normalized, ledger)
        build(ctx, geographic_graph(ctx, normalized))
        record = ctx.ledger.get("lookups", "manifest/current")
        assert record is not None
        (manifest,) = [o for o in record.outputs if o.path.endswith("manifest.json")]
        saved = json.loads(located(ctx.root, manifest.path).read_text())
        tables = {t["kind"]: t for t in saved["tables"]}
        assert PLATES | {"names"} <= set(tables)
        names = pq.read_table(located(ctx.root, tables["names"]["path"])).to_pylist()
        assert [(r["name"], r["kind"], r["language"]) for r in names] == [
            ("Stadt", "alternate", "de")
        ]
        codes = pq.read_table(located(ctx.root, tables["plate_codes"]["path"]))
        assert codes.num_rows == 1
        assert tables["plate_priors"]["rows"] == 0
        assert tables["plate_policy"]["rows"] == 1
