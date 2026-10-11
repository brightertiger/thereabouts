"""Plate-country pins come from its reviewed inventory and feed the plate tables."""

import importlib
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq
import pytest
import yaml

from pipeline.config import load
from pipeline.config.sources import SourceSettings
from pipeline.engines.artifacts import read_json
from pipeline.engines.plate_country.policy import base_policy, policy
from pipeline.pins.lock import read_lock
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.runner import run
from pipeline.sources import policy as source_policy
from pipeline.sources.contract import Proposer
from pipeline.stages import plate_country
from pipeline.stages.contract import Context, make_unit
from pipeline.stages.engine_recipes import plate_recipes

from ..test_plate_tables import rules, workspace
from .fixtures import source_context
from .proposal_server import Reply, publisher
from .test_plate_country_sources import wiki

__all__ = ["rules"]
INVENTORY = REPOSITORY / "config/policies/plate_country/sources.yaml"


def test_inventory_proposes_exactly_what_the_plates_pin_lacks() -> None:
    inventory = yaml.safe_load(INVENTORY.read_text())
    proposed = {name: spec for name, spec in inventory.items() if not spec.get("base")}
    plates = {f.name for f in read_lock(REPOSITORY / "pins.lock")["plates"].files}
    used = [r for rows in base_policy("formats").values() for r in rows] + [
        r
        for name in ("formats", "supplemental_formats", "templates", "state_tables")
        for r in policy(name)
    ]
    needed = ({"vehicle-stock.json"} | {r["source"] for r in used}) - plates
    assert needed == {n for n in proposed if not n.startswith("eval-")}
    assert len(needed) == 25
    for name in needed:
        spec = proposed[name]
        assert spec["kind"] == "wikipedia"
        assert f"oldid={spec['revision']}" in spec["download_url"]
    evaluation = yaml.safe_load(
        (REPOSITORY / "eval/plate_country/evaluation.yaml").read_text()
    )
    pages: dict[str, set[str]] = defaultdict(set)
    for rule in evaluation:
        pages[rule["source"]].add(str(rule["page_id"]))
    images = {r["image_source"] for r in evaluation if "image_source" in r}
    assert set(pages) | images == {n for n in proposed if n.startswith("eval-")}
    for name, ids in pages.items():
        selected = proposed[name]["download_url"].split("pageids=", 1)[1]
        assert set(selected.split("&", 1)[0].split("%7C")) == ids
    for name, spec in proposed.items():
        assert (spec.get("purpose") == "evaluation") == name.startswith("eval-")
        # SPDX identifiers (Public-Domain as the airports pin spells it).
        assert " " not in spec["license"]
        assert "?" not in spec["download_url"] or spec["kind"] != "image"


def test_plate_country_settings() -> None:
    settings = load().sources["plate_country"]
    assert settings.policies == {
        "sources": INVENTORY.relative_to(REPOSITORY).as_posix()
    }
    assert "proposal" not in settings.upstream
    assert "worldlicenseplates" not in str(settings.upstream) + str(settings.licence)
    inventory = yaml.safe_load(INVENTORY.read_text())
    recorded = sum(spec.get("size", 0) for spec in inventory.values())
    assert settings.limits.download_bytes >= 2 * recorded


def inventory(tmp_path: Path, server_url: str) -> SourceSettings:
    """A reviewed inventory: one base entry, the vehicle stock and a format page."""
    entries: dict[str, Any] = {"countries.csv": {"base": True}}
    for name in ("vehicle-stock.json", "wiki-QQ.json"):
        entries[name] = {
            "url": f"https://example.invalid/{name}",
            "download_url": f"{server_url}/{name}",
            "kind": "wikipedia",
            "revision": 123,
            "license": "CC-BY-SA-4.0",
            "attribution": "Wikipedia contributors",
            "sha256": "recorded-on-review",
        }
    (tmp_path / "inventory.yaml").write_text(yaml.safe_dump(entries))
    settings = load().sources["plate_country"]
    settings.policies = {"sources": "inventory.yaml"}
    settings.limits.retries = 0
    return settings


def plate_tables(root: Path, ctx: Context, available: set[str]) -> dict[str, int]:
    (recipe,) = plate_recipes(ctx, available)
    unit = make_unit(ctx, recipe, "test")
    outputs = plate_country.run(ctx, unit)
    saved = read_json(next(p for p in outputs if p.name == "manifest.json"))
    return {t["kind"]: t["rows"] for t in saved["tables"]} | {
        "plate_country": sum(
            row == "plate_country"
            for t in saved["tables"]
            if t["kind"] == "plate_formats"
            for row in pq.read_table(root / t["path"])["source"].to_pylist()
        )
    }


def test_loopback_pins_build_plate_tables_only_when_the_recipe_lists_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rules: dict[str, Any]
) -> None:
    stock = wiki(
        tmp_path / "stock.json",
        "<table><tr><th>Name</th><th>Rate</th><th>Vehicles</th><th>People</th>"
        "<th>Year</th></tr><tr><td>Example</td><td>10</td><td>1234</td>"
        "<td>12340</td><td>2020</td></tr></table>",
    )
    page = wiki(
        tmp_path / "qq.json",
        "<p>Example plates read AB-123.</p><table><tr><th>Code</th><th>Name</th>"
        "</tr><tr><td>QA</td><td>Qland</td></tr></table>",
    )
    payloads = {
        "vehicle-stock.json": Path(stock["path"]).read_bytes(),
        "wiki-QQ.json": Path(page["path"]).read_bytes(),
    }
    with publisher() as server:
        for name, body in payloads.items():
            server.routes["/" + name] = Reply(body)
        settings = inventory(tmp_path, server.url)
        proposer = cast(Proposer, importlib.import_module(settings.proposer))
        with monkeypatch.context() as patch:
            patch.setattr(source_policy, "REPOSITORY", tmp_path)
            pin = proposer.propose(settings)
    assert [f.name for f in pin.files] == ["vehicle-stock.json", "wiki-QQ.json"]
    assert all(f.url.startswith(server.url) for f in pin.files)
    assert pin.files[0].metadata["revision"] == 123
    assert pin.files[0].metadata["license"] == "CC-BY-SA-4.0"
    root = tmp_path / "ws"
    write_json(root / "normalized/plates/manifest.json", workspace(root))
    with Ledger(root, None, readonly=False) as ledger:
        ctx, _, stages = source_context(
            root,
            ledger,
            "plate_country",
            {f.name: (payloads[f.name], f.metadata) for f in pin.files},
        )
        run(ctx, stages)
        ctx.config.sources["plates"] = load().sources["plates"]
        ctx.config.sources["plate_country"].enabled = True
        unpinned = plate_tables(root, ctx, {"plates"})
        pinned = plate_tables(root, ctx, {"plates", "plate_country"})
    assert unpinned["plate_priors"] == 0 and unpinned["plate_country"] == 0
    assert unpinned["plate_formats"] == 1 and unpinned["plate_codes"] == 1
    assert pinned["plate_priors"] == 1 and pinned["plate_country"] == 1
    assert pinned["plate_formats"] == 2 and pinned["plate_codes"] == 2
