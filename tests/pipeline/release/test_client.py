"""The release stage delegates packing without depending on binary internals."""

import importlib
from pathlib import Path

import pytest

from pipeline.files import file_record
from pipeline.release import client
from pipeline.release.assemble import assemble
from pipeline.release.source import Row
from pipeline.runtime.jsonio import write_json
from thereabouts.mcp_service.dictionary import from_pack, notices

from .fixtures import fixture
from .synthetic import dataset as synthetic_dataset


def test_client_call_signature_and_checksum_validation(tmp_path: Path) -> None:
    snapshot, config, guard = fixture(tmp_path)
    dataset = tmp_path / "dataset"
    assemble(snapshot, dataset, config, guard, "identity")
    output = tmp_path / "packs" / "core"
    calls = []

    def writer(directory: str, family: str, target: str, options: Row) -> Row:
        calls.append((directory, family, target, options))
        destination = Path(target)
        destination.mkdir(parents=True)
        payload = destination / "client-owned.bin"
        payload.write_bytes(b"fake client output; no binary format implementation")
        manifest = {"files": [file_record(destination, payload)]}
        write_json(destination / "manifest.json", manifest)
        return manifest

    paths = client.write(dataset, "core", output, "2026.10", writer)
    assert len(paths) == 2
    directory, family, target, options = calls[0]
    assert (directory, family, target) == (str(dataset), "core", str(output))
    assert options["data_version"] == "2026.10"
    assert "OpenStreetMap contributors" in options["attribution"]
    assert set(options) == {
        "data_version",
        "sources",
        "attribution",
        "notices",
        "input_provenance",
    }

    def corrupt(directory: str, family: str, target: str, options: Row) -> Row:
        record = file_record(output, paths[0])
        paths[0].write_bytes(b"changed")
        return {"files": [record]}

    with pytest.raises(ValueError, match="checksum"):
        client.write(dataset, "core", output, "2026.10", corrupt)


def test_missing_binding_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", missing)
    with pytest.raises(ValueError, match="merged Rust client"):
        client.binding()


def test_core_pack_ships_the_dataset_dictionary_as_notices(tmp_path: Path) -> None:
    dataset, _ = synthetic_dataset(tmp_path)
    packs = tmp_path / "packs"
    writer = client.binding()
    for family in ("core", "postal"):
        client.write(dataset, family, packs / family, "2026.10", writer)
    assert set(notices(packs / "core")) == {
        "DATA_LICENSES.md",
        "DATA_DICTIONARY.md",
        "data_dictionary.json",
    }
    loaded = from_pack(packs / "core")
    assert loaded is not None and loaded.source == "pack"
    assert loaded.json_text == (dataset / "data_dictionary.json").read_text()
    assert loaded.markdown_text == (dataset / "DATA_DICTIONARY.md").read_text()
    assert set(notices(packs / "postal")) == {"DATA_LICENSES.md"}
