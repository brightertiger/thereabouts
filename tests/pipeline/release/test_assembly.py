"""Release content, relocation, byte caps and input verification."""

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from pipeline.cli import main
from pipeline.config import load
from pipeline.files import file_record
from pipeline.release import dictionary
from pipeline.release.assemble import assemble
from pipeline.release.source import external
from pipeline.release.verify import verify_dataset
from pipeline.runtime.jsonio import sha256_file, write_json

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
    assert len(manifest["statistics"]) == 20
    # The blocks table indexes packaging; content.json digests logical tables.
    content = json.loads((output / "content.json").read_text())
    assert set(content["tables"]) == set(manifest["statistics"]) - {"blocks"}
    cells = [t for t in manifest["tables"] if t["kind"] == "cells"]
    assert len(cells) == 1
    assert cells[0]["rows"] == 2
    assert (
        pq.read_table(output / cells[0]["path"])["city_method"].to_pylist()
        == ["rural_nearest_distant"] * 2
    )
    assert manifest["statistics"]["zone_tables"]["rows"] == 1
    notices = (output / "DATA_LICENSES.md").read_text()
    for table in manifest["tables"]:
        with pq.ParquetFile(output / table["path"]) as file:
            if "license" in file.schema_arrow.names:
                values = file.read(columns=["license"])["license"].to_pylist()
                assert all(value in notices for value in set(values) if value)
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


def test_referentially_open_datasets_are_refused(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path, closed=False)
    output = tmp_path / "dataset" / "2026.10"
    # The cells name country:MY and city:one, but no place defines them.
    with pytest.raises(ValueError, match="Dangling dataset place reference"):
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


def test_logical_place_key_cannot_be_null_despite_arrow_nullability(
    tmp_path: Path,
) -> None:
    snapshot, config, guard = fixture(tmp_path)
    entry = snapshot.tables["places"][0]
    path = snapshot.path(entry)
    schema = pq.read_schema(path)
    assert schema.field("place_id").nullable
    row: dict[str, object] = {field.name: None for field in schema}
    row["country_code"] = "MY"
    pq.write_table(pa.Table.from_pylist([row], schema=schema), path)
    for record in snapshot.manifest["tables"]:
        if record["path"] == entry.path:
            record.update(file_record(snapshot.root, path), rows=1)
    write_json(snapshot.root / "manifest.json", snapshot.manifest)
    snapshot = external(snapshot.root, config.h3)
    output = tmp_path / "dataset"
    with pytest.raises(ValueError, match=r"Null logical primary key: places\.place_id"):
        assemble(snapshot, output, config, guard, "identity")
    assert not output.exists()


def test_a_repeated_observation_key_is_refused(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    entry = snapshot.tables["zone_tables"][0]
    path = snapshot.path(entry)
    table = pq.read_table(path)
    pq.write_table(pa.concat_tables([table, table]), path)
    for record in snapshot.manifest["tables"]:
        if record["path"] == entry.path:
            record.update(file_record(snapshot.root, path), rows=2)
    write_json(snapshot.root / "manifest.json", snapshot.manifest)
    snapshot = external(snapshot.root, config.h3)
    output = tmp_path / "dataset"
    with pytest.raises(
        ValueError,
        match=r"Repeated logical primary key: zone_tables \(source, source_id\); "
        r"repeated values: \('timezones', 'one'\)$",
    ):
        assemble(snapshot, output, config, guard, "identity")
    assert not output.exists()


def documents(output: Path) -> dict[str, str]:
    return {
        name: (output / name).read_text()
        for name in ("README.md", "DATASET_CARD.md", "DATA_DICTIONARY.md")
    }


def test_dataset_ships_the_data_dictionary(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    output = tmp_path / "dataset" / "2026.10"
    assemble(snapshot, output, config, guard, "identity")
    listed = {record["path"] for record in verify_dataset(output)["files"]}
    for name, text in dictionary.documents().items():
        assert name in listed
        assert (output / name).read_text() == text
    readme = (output / "README.md").read_text()
    assert "`DATA_DICTIONARY.md`" in readme or "DATA_DICTIONARY.md  #" in readme


def test_subset_and_world_wording(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    subset = documents(assemble_into(snapshot, config, guard, tmp_path / "subset"))
    assert "This subset contains" in subset["README.md"]
    assert "spatial subset is not a complete" in subset["DATASET_CARD.md"]
    config.release.countries, config.release.blocks = [], []
    world = documents(assemble_into(snapshot, config, guard, tmp_path / "world"))
    assert "complete configured world export" in world["README.md"]
    assert "This subset" not in world["README.md"]
    assert "published subset" not in world["README.md"]
    assert "subset" not in world["DATASET_CARD.md"]
    for text in (*subset.values(), *world.values()):
        assert "<owner-bucket>" not in text
        assert "Owner-decision placeholders" not in text


def test_readme_names_a_configured_s3_destination(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    config.storage["s3_release"] = "s3://open-bucket/thereabouts"
    readme = assemble_into(snapshot, config, guard, tmp_path / "s3") / "README.md"
    text = readme.read_text()
    assert "s3://open-bucket/thereabouts/dataset/2026.10/cells/**/*.parquet" in text
    assert "dataset/2026.10/_SUCCESS" in text


def assemble_into(snapshot: Any, config: Any, guard: Any, root: Path) -> Path:
    output = root / "dataset" / "2026.10"
    assemble(snapshot, output, config, guard, "identity")
    return output
