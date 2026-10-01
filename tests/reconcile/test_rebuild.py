from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.schemas import SCHEMAS
from build_data.reconcile import __main__ as cli
from build_data.reconcile.build import build_country
from build_data.reconcile.common import policy
from build_data.reconcile.inputs import KINDS, extract
from build_data.reconcile.manifest import load

from .conftest import area, place, write_inputs


def test_cli_rebuild_resume_and_failed_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = write_inputs(
        tmp_path / "inputs",
        geonames=[place("town", "Town", 0.5, 0.5)],
        divisions=[],
        areas=[area("nation", "Nation", "country", (0, 0, 1, 1))],
    )
    land = root / "osm_land_areas.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [area("land", "Land", "land", (0, 0, 1, 1))], schema=SCHEMAS["areas"]
        ),
        land,
    )
    paths = {
        f"{s}_{k}": [str(root / f"{s}_{k}.parquet")]
        for s, kinds in KINDS.items()
        for k in kinds
    }
    sources = {s: {"source": s} for s in KINDS}
    monkeypatch.setattr(cli, "verified_inputs", lambda w: (paths, sources))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reconcile",
            "--countries",
            "ZZ",
            "--stage",
            "build",
            "--data-dir",
            str(tmp_path),
        ],
    )
    cli.main()
    workspace = Workspace(tmp_path)
    first = Path(load(workspace)["countries"]["ZZ"]["path"])
    stamp = first.stat().st_mtime_ns
    assert not list((workspace.work / "reconcile").rglob("*.parquet"))
    assert not list((workspace.work / "reconcile").rglob("*-links.sqlite"))
    original_extract = extract

    def fail_extract(*args: object) -> Path:
        raise AssertionError("verified country must skip deleted intermediates")

    monkeypatch.setattr(cli, "extract", fail_extract)
    cli.main()
    assert first.stat().st_mtime_ns == stamp
    monkeypatch.setattr(cli, "extract", original_extract)
    changed = policy()
    changed["nearest_m"] = 49000
    monkeypatch.setattr(cli, "policy", lambda: changed)
    original_build = build_country

    def fail_build(*args: object) -> Path:
        raise OSError("interrupted replacement")

    monkeypatch.setattr(cli, "build_country", fail_build)
    with pytest.raises(OSError, match="interrupted replacement"):
        cli.main()
    assert first.exists()
    assert not read_json(tmp_path / "reconciled/manifest.json")["completed"]
    monkeypatch.setattr(cli, "build_country", original_build)
    cli.main()
    second = Path(load(workspace)["countries"]["ZZ"]["path"])
    assert second.exists() and not first.exists()
