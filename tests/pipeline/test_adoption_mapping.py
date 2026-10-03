"""Select retained generations and preserve absent reconciliation evidence."""

from pathlib import Path

import pytest

from pipeline.migration.adoption import _verify
from pipeline.migration.candidates import Candidate
from pipeline.migration.inventory import Inventory
from pipeline.migration.mapping import destination
from pipeline.migration.paths import portable
from pipeline.runtime.jsonio import Object, digest
from pipeline.runtime.records import Output
from pipeline.runtime.verification import Verifier


def test_active_normalization_is_selected_without_adopting_old_lookup_joins(
    tmp_path: Path,
) -> None:
    inventory = Inventory(tmp_path, active_prefix="city_normalized")
    output: Object = {
        "path": "city_normalized/cells/block.parquet",
        "size": 0,
        "sha256": digest("fixture"),
    }
    mapped = destination(
        inventory, "normalize-cells.cells", "city_normalized:block", [output]
    )
    assert (mapped.stage, mapped.unit_id) == ("normalize_cells", "block/block")
    output["path"] = "work/pilot/cells/block.parquet"
    assert (
        destination(inventory, "normalize-cells.cells", "pilot:block", [output]).stage
        is None
    )
    assert destination(inventory, "golden.lookup", "airports", []).stage is None
    with pytest.raises(ValueError, match="No adoption mapping"):
        destination(inventory, "unrecognized.builder", "block", [output])


def test_equal_base_hashes_do_not_erase_block_identity(tmp_path: Path) -> None:
    sha = digest("identical empty parquet")
    first = Output("base_cells/first.parquet", 0, sha)
    second = Output("base_cells/second.parquet", 0, sha)
    inventory = Inventory(
        tmp_path, base_units={("cells", "first"): first, ("cells", "second"): second}
    )
    original: Object = {"path": "golden/cells/second.parquet", "size": 0, "sha256": sha}
    assert inventory.output(original, base=True) == second


def test_absence_exception_preserves_recorded_hash_and_rejects_present_corruption(
    tmp_path: Path,
) -> None:
    output = Output("reconciled/land.sqlite3", 10, digest("recorded bytes"))
    candidate = Candidate("reconcile", "land/world", outputs={output.path: output})
    _verify(candidate, Verifier(tmp_path))
    assert candidate.absent == [output.path]
    assert candidate.outputs[output.path] == output
    target = tmp_path / output.path
    target.parent.mkdir()
    target.write_bytes(b"bad")
    with pytest.raises(ValueError, match="Cannot adopt"):
        _verify(candidate, Verifier(tmp_path))


def test_paths_are_translated_without_rewriting_overture_json_pointers(
    tmp_path: Path,
) -> None:
    value: Object = {
        "inputs": [{"path": "/old/checkout/data/raw/source/input.zip"}],
        "audit": [{"path": "/properties/names/primary"}],
    }
    assert portable(value, tmp_path) == {
        "inputs": [{"path": "raw/source/input.zip"}],
        "audit": [{"path": "/properties/names/primary"}],
    }


@pytest.mark.parametrize("prefix", ["other/", "work/unrelated/", "reconciled-other/"])
def test_reconcile_absence_is_limited_to_documented_directories(
    tmp_path: Path, prefix: str
) -> None:
    output = Output(prefix + "missing.sqlite3", 10, digest("recorded bytes"))
    candidate = Candidate("reconcile", "land/world", outputs={output.path: output})
    with pytest.raises(ValueError, match="Cannot adopt"):
        _verify(candidate, Verifier(tmp_path))


@pytest.mark.parametrize(
    "stage", ["geonames.extract", "geonames.index", "overture.index"]
)
def test_extraction_and_index_payloads_remain_owned_by_normalize(
    tmp_path: Path, stage: str
) -> None:
    source = stage.split(".")[0]
    inventory = Inventory(tmp_path, sources={source: {}})
    mapping = destination(inventory, stage, "auxiliary", [])
    assert (mapping.stage, mapping.unit_id) == ("normalize", source)


@pytest.mark.parametrize(
    ("source", "prefix"),
    [
        ("geonames", "work/overture/"),
        ("overture", "work/geonames/"),
        ("geonames", "work/geonames-other/"),
        ("geonames", "normalized/geonames/"),
        ("overture", "raw/overture/"),
        ("ghsl", "work/geonames/"),
    ],
)
def test_auxiliary_absence_cannot_escape_approved_source_and_prefix(
    tmp_path: Path, source: str, prefix: str
) -> None:
    output = Output(prefix + "missing", 10, digest("recorded bytes"))
    candidate = Candidate("normalize", source, outputs={output.path: output})
    with pytest.raises(ValueError, match="Cannot adopt"):
        _verify(candidate, Verifier(tmp_path))
