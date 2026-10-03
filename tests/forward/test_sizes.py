"""Compressed query/evidence ceilings and independent writer accounting."""

import json
from pathlib import Path

import pytest

from benchmarks.forward_sizes import measure
from tools.source_fixture import read_source

PACKS = Path(__file__).parents[1] / "fixtures/packs"


@pytest.mark.parametrize(
    ("family", "ceiling"),
    [
        ("ip", 16),
        ("postal", 14),
        ("airports", 40),
        ("locode", 40),
        ("phone", 40),
        ("plates", 40),
    ],
)
def test_all_compressed_blocks_budget_and_writer_accounting(
    family: str, ceiling: int
) -> None:
    pack = PACKS / f"{family}-sample"
    actual = measure(pack)
    report = json.loads((pack / "manifest.json").read_text())["storage"]
    assert actual["all_compressed_bytes_per_row"] <= ceiling
    assert report["source_rows"] == actual["source_rows"]
    source = read_source(PACKS.parent / f"{family}-source.json.gz")
    assert report["source_rows"] == len(source["rows"])
    assert report["query_compressed_bytes"] == actual["compressed_query_bytes"]
    assert report["evidence_compressed_bytes"] == actual["compressed_evidence_bytes"]
    assert report["data_artifact_bytes"] == sum(
        size
        for role, size in actual["artifact_bytes_by_role"].items()
        if role not in {"catalogue", "metadata", "notice"}
    )
    assert report["catalogue_bytes"] == actual["artifact_bytes_by_role"].get(
        "catalogue", 0
    )
    assert report["metadata_bytes"] == actual["artifact_bytes_by_role"]["metadata"]


def test_forward_fixtures_fit_committed_budget() -> None:
    packs = sum(
        p.stat().st_size
        for pack in PACKS.iterdir()
        if pack.is_dir() and pack.name not in {"core-sample", "core-synthetic"}
        for p in pack.rglob("*")
        if p.is_file()
    )
    extracts = sum(p.stat().st_size for p in PACKS.parent.glob("*-source.json.gz"))
    vectors = sum(
        p.stat().st_size
        for p in PACKS.parent.glob("*-vectors.json")
        if not p.name.startswith("core-")
    )
    assert packs + extracts + vectors < 10_000_000
