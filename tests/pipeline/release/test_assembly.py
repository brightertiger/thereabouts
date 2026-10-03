"""Release content, relocation, byte caps and input verification."""

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from pipeline.cli import main
from pipeline.config import load
from pipeline.release.assemble import assemble
from pipeline.release.verify import verify_dataset
from pipeline.runtime.jsonio import sha256_file

from .fixtures import fixture


def test_coalescing_readme_and_relocation(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    before = {
        entry.path: sha256_file(snapshot.path(entry))
        for entries in snapshot.tables.values()
        for entry in entries
    }
    output = tmp_path / "dataset" / "2026.10"
    paths = assemble(snapshot, output, config, guard, "identity")
    manifest = verify_dataset(output)
    assert len(manifest["statistics"]) == 14
    cells = [t for t in manifest["tables"] if t["kind"] == "cells"]
    assert len(cells) == 1
    assert cells[0]["rows"] == 2
    assert (
        pq.read_table(output / cells[0]["path"])["city_method"].to_pylist()
        == ["rural_nearest_distant"] * 2
    )
    assert manifest["statistics"]["zone_tables"]["rows"] == 1
    assert all(not Path(record["path"]).is_absolute() for record in manifest["files"])
    text = (output / "README.md").read_text()
    for name, schema in manifest["schemas"].items():
        assert f"### `{name}`" in text
        assert all(f"`{column['name']}`" in text for column in schema["columns"])
    assert "OpenStreetMap contributors, Overture Maps Foundation" in text
    assert "plates" not in manifest["sources"]
    assert text.count("```python") == 3
    assert "{{" not in text
    assert assemble(snapshot, output, config, guard, "identity") == paths
    with pytest.raises(ValueError, match="immutable"):
        assemble(snapshot, output, config, guard, "changed")
    moved = tmp_path / "moved"
    output.rename(moved)
    assert verify_dataset(moved) == manifest
    assert all(
        sha256_file(snapshot.root / path) == value for path, value in before.items()
    )


def test_cap_cleans_only_owned_staging_and_corruption_refuses(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    output = tmp_path / "dataset" / "2026.10"
    config.release.dataset.max_output_bytes = 100
    with pytest.raises(ValueError, match="cap exceeded"):
        assemble(snapshot, output, config, guard, "identity")
    assert not output.exists()
    assert not list(output.parent.iterdir())
    config.release.dataset.max_output_bytes = 3_000_000_000
    source = snapshot.path(snapshot.tables["cells"][0])
    source.write_bytes(b"corrupt")
    with pytest.raises((ValueError, OSError)):
        assemble(snapshot, output, config, guard, "identity")
    assert not output.exists()


@pytest.mark.parametrize(
    "override",
    [
        "release.version=2026.13",
        "release.version=2026.10.0",
        "release.dataset.max_output_bytes=0",
        "release.dataset.cell_group_resolution=4",
        "release.packs.families=[unknown]",
        "release.publish.multipart_bytes=1",
        "content.merge_fan_in=1",
    ],
)
def test_invalid_release_configuration(override: str) -> None:
    with pytest.raises(ValueError):
        load(overrides=[override])


def test_prepare_cannot_write_into_input_root(tmp_path: Path) -> None:
    snapshot, _, _ = fixture(tmp_path)
    assert (
        main(
            [
                "release",
                "prepare",
                "--from",
                str(snapshot.root),
                "--root",
                str(snapshot.root / "output"),
                "--version",
                "2026.10",
            ]
        )
        == 2
    )
    assert not (snapshot.root / "output").exists()


def test_empty_batches_do_not_create_row_groups_and_changes_compare_content(
    tmp_path: Path,
) -> None:
    snapshot, config, guard = fixture(tmp_path)
    first = tmp_path / "dataset" / "2026.10"
    assemble(snapshot, first, config, guard, "first")
    manifest = verify_dataset(first)
    for table in manifest["tables"]:
        if not table["rows"]:
            assert pq.read_metadata(first / table["path"]).num_row_groups == 0
    config.release.version = "2026.10.1"
    second = tmp_path / "dataset" / config.release.version
    assemble(snapshot, second, config, guard, "second", first)
    updated = verify_dataset(second)
    assert updated["logical_sha256"] == manifest["logical_sha256"]
    lines = (second / "CHANGES.md").read_text().splitlines()
    changes = [line for line in lines if line.startswith("| ")][2:]
    assert changes and all(line.endswith("| no |") for line in changes)
