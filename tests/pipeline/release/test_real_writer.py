"""The pipeline runner builds real packs and a locally installable release."""

import json
import shutil
import subprocess
import sys
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import h3
import pyarrow.parquet as pq
import pytest

from pipeline.config import load
from pipeline.release.prepared import packs
from pipeline.release.publish import inventory
from pipeline.runtime.jsonio import sha256_file, write_json
from thereabouts import Geocoder, _core

FIXTURES = Path(__file__).parents[2] / "fixtures/datasets"


def dataset(root: Path) -> None:
    """Coalesce frozen synthetic Parquet; expected lookup JSON is never an input."""
    shutil.copytree(FIXTURES / "forward-synthetic", root)
    value = json.loads((root / "golden/manifest.json").read_text())
    base = FIXTURES / "core-synthetic"
    core = json.loads((base / "golden/manifest.json").read_text())
    for record in core["tables"]:
        if record["kind"] in {"timezone_cells", "zone_tables"}:
            destination = root / record["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(base / record["path"], destination)
            value["tables"].append(record)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tables = []
    for row in value["tables"]:
        if row["kind"] == "cells":
            if row["rows"]:
                groups[h3.cell_to_parent(row["block"], 1)].append(row)
        else:
            tables.append(row)
    for parent, rows in groups.items():
        rows.sort(key=lambda row: row["block"])
        path = root / f"cells/group={parent}/part.parquet"
        path.parent.mkdir(parents=True)
        schema = pq.ParquetFile(root / rows[0]["path"]).schema_arrow
        with pq.ParquetWriter(path, schema) as stream:
            for row in rows:
                stream.write_table(pq.ParquetFile(root / row["path"]).read())
        tables.append(
            {
                "kind": "cells",
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
                "rows": sum(row["rows"] for row in rows),
                "blocks": [
                    dict(block=row["block"], row_group=i, rows=row["rows"])
                    for i, row in enumerate(rows)
                ],
            }
        )
    (root / "DATA_LICENSES.md").write_text("Synthetic fixture; public domain.\n")
    value.update(tables=tables, files=tables, data_root=".", sources={})
    write_json(root / "manifest.json", value)


def test_runner_real_writer_and_console_install(tmp_path: Path) -> None:
    root = tmp_path / "dataset/2026.10"
    dataset(root)
    config = load(
        overrides=[
            "release.enabled=true",
            'release.version="2026.10"',
            "release.packs.families=[postal,airports,core]",
            "resources.workers=2",
        ]
    )
    assert packs(config, tmp_path)["completed"] == 5  # dataset, 3 families, index
    assert packs(config, tmp_path)["completed"] == 0
    release = tmp_path / "packs/2026.10"
    index = json.loads((release / "index.json").read_text())
    assert set(index["datasets"]["2026.10"]["packs"]) == {"core", "postal", "airports"}
    for family in config.release.packs.families:
        assert _core.verify_pack(str(release / family))["family"] == family
    uploads = inventory(
        root, {f: release / f for f in config.release.packs.families}, "2026.10"
    )
    assert {u.remote for u in uploads} >= {
        "packs/2026.10/index.json",
        "packs/2026.10/core.tar",
        "packs/2026.10/postal.tar",
        "packs/2026.10/airports.tar",
    }
    store = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "thereabouts",
            "--data-dir",
            str(store),
            "data",
            "install",
            "core",
            "postal",
            "airports",
            "--from",
            str(release),
            "--yes",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    with Geocoder(data_dir=store) as geo:
        assert geo.postal("00100", country="AA").status == "matched"
        assert geo.airport("ZZZ").status == "ambiguous"
    archive = release / "postal.tar"
    with tarfile.open(archive) as reader:
        member = next(m for m in reader if m.size > 10)
        offset = member.offset_data
    with archive.open("r+b") as stream:
        stream.seek(offset)
        stream.write(b"corrupt")
    with pytest.raises(ValueError, match=r"checksum|archive"):
        packs(config, tmp_path)


def test_forward_release_requires_explicit_core(tmp_path: Path) -> None:
    dataset(tmp_path / "dataset/2026.10")
    config = load(
        overrides=[
            "release.enabled=true",
            'release.version="2026.10"',
            "release.packs.families=[postal]",
        ]
    )
    with pytest.raises(ValueError, match="include the core"):
        packs(config, tmp_path)
