"""A normalize unit's partitions are exactly its Parquet outputs."""

import json
from pathlib import Path
from typing import Any

import pytest

from pipeline.runtime.ledger import Ledger
from pipeline.runtime.outputs import selected
from pipeline.runtime.runner import run
from pipeline.stages.sources import PARTITIONS

from .sources.fixtures import archive, source_context
from .sources.test_shapes import shapes
from .test_recorded_content import boundary_payloads


def land_payloads(root: Path) -> dict[str, tuple[bytes, dict[str, Any]]]:
    members = shapes(root, ["FID"], [["1"], ["2"]])
    members["README.txt"] = (
        b"2 Polygon features\nDate of the data used is 2026-10-01T00:00:00Z\n"
    )
    return {"land.zip": (archive(members), {})}


@pytest.mark.parametrize("name", ["geoboundaries", "osm_land"])
def test_partitions_are_exactly_the_parquet_outputs(tmp_path: Path, name: str) -> None:
    payloads = (
        boundary_payloads(tmp_path)
        if name == "geoboundaries"
        else land_payloads(tmp_path)
    )
    with Ledger(tmp_path, None, readonly=False) as ledger:
        runtime, source, stages = source_context(tmp_path, ledger, name, payloads)
        source.pin.metadata["country_reference"] = {"GBR": {"alpha2": "GB"}}
        run(runtime, stages)
        record = ledger.get("normalize", name)
        assert record is not None
        manifest = json.loads((source.normalized / "manifest.json").read_bytes())
        partitions = {part["path"] for part in manifest["partitions"]}
        read = selected(record.outputs, PARTITIONS, record.inputs_hash)
        assert partitions and {output.path for output in read} == partitions
        assert {output.path for output in record.outputs} > partitions
