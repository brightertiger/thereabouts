"""The lookups manifest blocks on reviewed countries and records the rest."""

from pathlib import Path

from pipeline.config import policies
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.stages import lookups
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
