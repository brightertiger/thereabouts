"""The committed binary example must remain readable without build inputs."""

from pathlib import Path

from thereabouts.packs.layout import CITY_METHODS
from thereabouts.packs.spatial import Spatial
from thereabouts.packs.verify import verify


def test_committed_binary_fixture() -> None:
    path = Path(__file__).parents[1] / "fixtures/serving"
    value = verify(path)
    assert value["data_version"] == "synthetic"
    assert value["nearest"] == {
        "distant_over_m": 25000,
        "cutoff_m": 50000,
        "exact_distance": False,
    }
    assert value["place_count"] == 5
    methods = set()
    encodings = set()
    rows = 0
    for record in value["files"]:
        if record["kind"] != "cells":
            continue
        spatial = Spatial(path / record["path"], value["place_count"])
        try:
            for block in spatial.blocks.values():
                rows += block.count
                encodings.add(block.width)
                for index in range(block.count):
                    methods.add(CITY_METHODS[spatial.label(block, index)[3] & 7])
        finally:
            spatial.close()
    assert rows == 33
    assert methods == set(CITY_METHODS)
    assert encodings == {0, 1}
