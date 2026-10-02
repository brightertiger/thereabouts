import importlib
import shutil
from pathlib import Path
from typing import Any

import pytest

from build_data.serve.export import export
from thereabouts.client import Geocoder
from thereabouts.packs.exact import Exact
from thereabouts.packs.jsonio import canonical, parse, sha256
from thereabouts.packs.verify import verify

from .fixtures import snapshot


def test_exports_are_minimal_relocatable_idempotent_and_keep_row_counts(
    tmp_path: Path,
) -> None:
    manifest, release = snapshot(tmp_path / "input")
    for family in ("postal", "airports"):
        path = export(
            manifest, release, tmp_path / family, family=family, shard_bytes=2048
        )
        value = verify(path)
        assert value["family"] == family and value["coverage"] == "keys"
        assert value["source_rows"] == (7 if family == "postal" else 4)
        assert value["unindexed_rows"] == (0 if family == "postal" else 1)
        assert value["place_count"] == (6 if family == "postal" else 5)
        assert not any(row["kind"] == "cells" for row in value["files"])
        stamps = {
            file.name: file.stat().st_mtime_ns
            for file in path.iterdir()
            if file.is_file()
        }
        assert export(manifest, release, path, family=family, shard_bytes=2048) == path
        assert all(
            (path / name).stat().st_mtime_ns == stamp for name, stamp in stamps.items()
        )
        moved = tmp_path / (family + "-moved")
        shutil.copytree(path, moved)
        with Geocoder(moved, verify=True) as geo:
            answer = (
                geo.postal("AMB", country="AA")
                if family == "postal"
                else geo.airport("ZZZ", scheme="iata")
            )
            assert answer.status == "ambiguous"
        for record in value["files"]:
            if record["kind"] != "exact":
                continue
            shard = Exact(path / record["path"], record["max_record_bytes"])
            try:
                assert (
                    max(shard.record(i)[-1] for i in range(shard.count))
                    == record["max_record_bytes"]
                )
            finally:
                shard.close()
        with pytest.raises(FileExistsError):
            export(manifest, release, path, family=family, shard_bytes=4096)


def test_interrupted_exact_shards_resume_with_byte_identical_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, release = snapshot(tmp_path / "input")
    encoding = importlib.import_module("build_data.serve_codes.encoding")
    original = encoding.Buffer.write
    calls = []

    def fail(self: Any, path: Path) -> None:
        calls.append(path)
        if len(calls) == 2:
            raise OSError("interrupted")
        original(self, path)

    monkeypatch.setattr(encoding.Buffer, "write", fail)
    with pytest.raises(OSError, match="interrupted"):
        export(manifest, release, tmp_path / "pack", family="airports", shard_bytes=512)
    first = calls[0]
    stamp, digest = first.stat().st_mtime_ns, sha256(first)
    monkeypatch.setattr(encoding.Buffer, "write", original)
    output = export(
        manifest, release, tmp_path / "pack", family="airports", shard_bytes=512
    )
    assert (output / first.name).stat().st_mtime_ns == stamp
    assert sha256(output / first.name) == digest
    second = export(
        manifest, release, tmp_path / "clean", family="airports", shard_bytes=512
    )
    assert (output / "manifest.json").read_bytes() == (
        second / "manifest.json"
    ).read_bytes()


def test_unattributed_observation_is_rejected(tmp_path: Path) -> None:
    manifest, release = snapshot(tmp_path / "input")
    value = parse(release.read_bytes())
    value["sources"][0]["release"] = "different-release"
    release.write_bytes(canonical(value))
    with pytest.raises(ValueError, match="attribution"):
        export(manifest, release, tmp_path / "bad", family="postal")


def test_unlocated_only_pack_needs_no_catalogue(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from build_data.serve.checkpoints import file_record

    manifest, release = snapshot(tmp_path / "input")
    value = parse(manifest.read_bytes())
    record = next(row for row in value["tables"] if row["kind"] == "airports")
    path = tmp_path / "input" / record["path"]
    table = pq.ParquetFile(path).read()
    rows = [row for row in table.to_pylist() if row["h3"] is None]
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    record.update(file_record(path, tmp_path / "input"), rows=len(rows))
    manifest.write_bytes(canonical(value))
    output = export(manifest, release, tmp_path / "unlocated", family="airports")
    with Geocoder(output, verify=True) as geo:
        assert geo.info()["packs"]["airports"]["place_count"] == 0
        candidate = geo.airport("ZZZ", scheme="iata").require_one()
        assert candidate and candidate.place and candidate.country is None
        assert candidate.place.country_code == "BB"


def test_changed_join_cannot_silently_relabel_a_source_row(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    from build_data.serve.checkpoints import file_record

    manifest, release = snapshot(tmp_path / "input")
    value = parse(manifest.read_bytes())
    record = next(row for row in value["tables"] if row["kind"] == "postal_codes")
    path = tmp_path / "input" / record["path"]
    table = pq.ParquetFile(path).read()
    rows = table.to_pylist()
    rows[0]["city_id"] = "city:synthetic:unused"
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), path)
    record.update(file_record(path, tmp_path / "input"))
    manifest.write_bytes(canonical(value))
    with pytest.raises(ValueError, match="cell join"):
        export(manifest, release, tmp_path / "bad", family="postal")
