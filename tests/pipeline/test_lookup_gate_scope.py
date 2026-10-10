"""The lookups manifest blocks on reviewed countries and records the rest."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from pipeline.config import policies
from pipeline.config.reviews import Review
from pipeline.engines.artifacts import read_json
from pipeline.engines.store.codec import Row
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Dependency, Recipe
from pipeline.stages import lookup_manifest, lookups
from pipeline.stages.contract import Unit
from pipeline.stages.engine_data import Geography

from .helpers import context


def test_only_the_manifest_carries_the_gate_scope(tmp_path: Path) -> None:
    with Ledger(tmp_path, None, readonly=False) as ledger:
        configure = lookups.parameters(
            context(tmp_path, ledger), Geography(["BE", "DE"], {})
        )
        manifest = configure(Recipe("lookups", "manifest/current"))
        spatial = configure(Recipe("lookups", "spatial/postal_codes/BE"))
    gates = manifest.parameters["gates"]
    assert gates["blocking_scope"] == "reviewed"
    pilots = {
        *policies.reconcile()["pilot"],
        *policies.cities()["pilot"],
    }
    # US has a reviewed boundary exception; DE is in neither pilot.
    assert pilots | {"US"} <= set(gates["reviewed"])
    assert "DE" not in gates["reviewed"]
    assert gates["reviewed"] == sorted(gates["reviewed"])
    assert manifest.reads == ("config/reviews/cities-pilot.yaml",)
    assert "gates" not in spatial.parameters
    assert (REPOSITORY / lookups.QUALITY_POLICY).is_file()


def boundary(cc: str, lost: int) -> Row:
    return {
        "country": cc,
        "city_id": f"city:{cc}",
        "references": [],
        "lost_cells": lost,
        "lost_to": {"city:other": lost},
        "loss_examples": [],
    }


def footprint(share: float) -> Row:
    return {"city_id": "city:large", "after": {"eligible": 100, "share": share}}


def report(
    losses: Sequence[Row] = (), footprints: Sequence[Row] = (), named: bool = True
) -> Row:
    return {
        "footprints": list(footprints),
        "neighbours": [],
        "all_boundaries": list(losses),
        "named": [] if named else [{"country": "DE", "passed": False}],
    }


def publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reports: dict[str, Row],
    scope: str = "reviewed",
) -> list[Path]:
    """Publish quality reports alone; table measurements find no errors."""
    root = tmp_path / "lookups"
    io, names = lookup_manifest.io, lookup_manifest.names
    monkeypatch.setattr(io, "receipt", lambda *a, **k: reports[a[2].split("/")[1]])
    monkeypatch.setattr(io, "local", lambda ctx, tables: tables)
    monkeypatch.setattr(lookup_manifest, "measure", lambda *a, **k: {})
    monkeypatch.setattr(lookup_manifest, "reference_checks", lambda *a: {})
    monkeypatch.setattr(names, "dangling", lambda *a: [])
    monkeypatch.setattr(lookup_manifest.reviews, "load", lambda *a: Review(True))
    monkeypatch.setattr(lookup_manifest, "resolver", lambda *a: lambda loss: [])
    gates = {"blocking_scope": scope, "reviewed": ["GB"]}
    recipe = Recipe(
        "lookups",
        "manifest/current",
        {"policy": {}, "gates": gates},
        tuple(Dependency("normalize_cells", "quality/" + cc) for cc in reports),
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        ctx = context(tmp_path, ledger)
        unit = Unit(recipe, "identity", "inputs", "dependencies")
        return lookup_manifest.publish(ctx, unit, root, {})


def test_reviewed_country_boundary_loss_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = {"GB": report([boundary("GB", 2)]), "DE": report([boundary("DE", 3)])}
    with pytest.raises(ValueError, match="Stored dataset gate failed"):
        publish(tmp_path, monkeypatch, reports)
    root = tmp_path / "lookups"
    quality = read_json(root / "quality.json")
    assert quality["failed_spatial_gates"]["all_boundaries"] == [boundary("GB", 2)]
    assert quality["advisory_spatial_gates"]["all_boundaries"] == [boundary("DE", 3)]
    assert not (root / "manifest.json").exists()


def test_reviewed_country_footprint_failure_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = {"GB": report(footprints=[footprint(0.98)])}
    with pytest.raises(ValueError, match="Stored dataset gate failed"):
        publish(tmp_path, monkeypatch, reports)
    quality = read_json(tmp_path / "lookups/quality.json")
    assert quality["failed_spatial_gates"]["footprints"] == [
        {**footprint(0.98), "country": "GB"}
    ]


def test_unreviewed_country_findings_are_advisory_and_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = {
        "GB": report(footprints=[footprint(1.0)]),
        "DE": report(
            [boundary("DE", 3), boundary("DE", 4)], [footprint(0.5), footprint(1.0)]
        ),
        "FR": report(footprints=[footprint(0.9)]),
    }
    quality, manifest, pointer = publish(tmp_path, monkeypatch, reports)
    assert pointer.is_file() and manifest.is_file()
    value = read_json(quality)
    assert not any(value["failed_spatial_gates"].values())
    assert value["advisory_spatial_gates"] == {
        "all_boundaries": [boundary("DE", 3), boundary("DE", 4)],
        "footprints": [
            {**footprint(0.5), "country": "DE"},
            {**footprint(0.9), "country": "FR"},
        ],
    }
    assert value["boundary_losses"] == [boundary("DE", 3), boundary("DE", 4)]
    advisory = {
        "countries": 2,
        "boundary_losses": 2,
        "lost_cells": 7,
        "footprint_failures": 2,
    }
    assert value["gate_scope"] == {
        "blocking_scope": "reviewed",
        "reviewed_countries": ["GB"],
        "blocking": {
            "countries": 0,
            "boundary_losses": 0,
            "lost_cells": 0,
            "footprint_failures": 0,
        },
        "advisory": advisory,
        "by_country": {
            "DE": {
                "reviewed": False,
                "boundary_losses": 2,
                "lost_cells": 7,
                "footprint_failures": 1,
            },
            "FR": {
                "reviewed": False,
                "boundary_losses": 0,
                "lost_cells": 0,
                "footprint_failures": 1,
            },
        },
    }
    assert read_json(manifest)["quality_gates"] == {
        "blocking_scope": "reviewed",
        "reviewed_countries": ["GB"],
        "advisory": advisory,
    }


def test_named_point_failures_block_in_any_country(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="Stored dataset gate failed"):
        publish(tmp_path, monkeypatch, {"DE": report(named=False)})


def test_all_scope_blocks_unreviewed_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = {"DE": report([boundary("DE", 3)], [footprint(0.5)])}
    with pytest.raises(ValueError, match="Stored dataset gate failed"):
        publish(tmp_path, monkeypatch, reports, scope="all")
    root = tmp_path / "lookups"
    quality = read_json(root / "quality.json")
    assert quality["failed_spatial_gates"]["all_boundaries"] == [boundary("DE", 3)]
    assert len(quality["failed_spatial_gates"]["footprints"]) == 1
    assert quality["advisory_spatial_gates"] == {"all_boundaries": [], "footprints": []}
    assert quality["gate_scope"]["by_country"]["DE"]["reviewed"] is False
    assert not (root / "manifest.json").exists()
