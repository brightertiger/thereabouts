"""Release archives are deterministic tar.zst files indexed by format 3."""

import json
import shutil
from pathlib import Path
from uuid import uuid4

import fsspec
import pytest

from pipeline.config.release import PublishSettings
from pipeline.config.schema import Resources
from pipeline.release import bundle
from pipeline.release.publish import Upload, publish
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.resources import ResourceGuard
from thereabouts import CorruptPackError, _core

PACKS = Path(__file__).parents[2] / "fixtures/packs"


def guard(root: Path) -> ResourceGuard:
    return ResourceGuard(
        root, Resources(), free=lambda _: 10**12, used=lambda _: 0, rss=lambda: 0
    )


def release(root: Path, version: str = "2026.10") -> Path:
    """Two families laid out as the packs stage writes them."""
    directory = root / version
    for family, fixture in [("core", "core-synthetic"), ("phone", "phone-synthetic")]:
        shutil.copytree(PACKS / fixture, directory / family)
        bundle.archive(directory / family, guard(root))
    bundle.index(directory, version, ["core", "phone"])
    return directory


def test_archives_are_deterministic_and_indexed_with_unpacked_size(
    tmp_path: Path,
) -> None:
    one = release(tmp_path / "one")
    two = release(tmp_path / "two")
    for family in ("core", "phone"):
        first = (one / f"{family}.tar.zst").read_bytes()
        assert first == (two / f"{family}.tar.zst").read_bytes()
        assert first[:4] == b"\x28\xb5\x2f\xfd"
    value = json.loads((one / "index.json").read_text())
    assert value["format"] == 3
    entry = value["datasets"]["2026.10"]["packs"]["phone"]
    path = one / "phone.tar.zst"
    assert entry == {
        "url": "phone.tar.zst",
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "unpacked_size": _core.inspect_archive(str(path))["unpacked_size"],
        "format_minor": 2,
    }
    # The plain ustar stream is the unpacked size: headers, padded files, terminator.
    assert entry["unpacked_size"] % 512 == 0 and entry["unpacked_size"] > entry["size"]
    # Rebuilding the same pack is a no-op; a changed archive is refused.
    assert bundle.archive(one / "phone", guard(tmp_path)) == path
    shutil.copy(one / "core.tar.zst", path)
    with pytest.raises(ValueError, match="differs from its pack"):
        bundle.archive(one / "phone", guard(tmp_path))


def test_archive_refuses_a_pack_that_differs_from_its_manifest(
    tmp_path: Path,
) -> None:
    pack = tmp_path / "phone"
    shutil.copytree(PACKS / "phone-synthetic", pack)
    victim = next(p for p in sorted(pack.iterdir()) if p.name != "manifest.json")
    content = bytearray(victim.read_bytes())
    content[-1] ^= 1
    victim.write_bytes(bytes(content))
    with pytest.raises(CorruptPackError, match="differs from its manifest"):
        bundle.archive(pack, guard(tmp_path))
    assert not (tmp_path / "phone.tar.zst").exists()


def test_aggregate_merges_versions_with_relative_urls(tmp_path: Path) -> None:
    current = json.loads((release(tmp_path) / "index.json").read_text())
    merged = bundle.merge(None, "2026.10", current)
    assert merged["datasets"]["2026.10"]["packs"]["core"]["url"] == (
        "2026.10/core.tar.zst"
    )
    later = json.loads(json.dumps(current).replace("2026.10", "2026.11"))
    both = bundle.merge({**merged, "latest": "2026.10"}, "2026.11", later)
    assert set(both["datasets"]) == {"2026.10", "2026.11"}
    assert both["latest"] == "2026.10"  # unknown fields survive a merge
    assert bundle.merge(both, "2026.10", current) == both
    changed = json.loads(json.dumps(current))
    changed["datasets"]["2026.10"]["packs"]["core"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match=r"already lists another 2026\.10"):
        bundle.merge(both, "2026.10", changed)
    with pytest.raises(ValueError, match="not format 3"):
        bundle.merge({"format": 2, "datasets": {}}, "2026.10", current)
    with pytest.raises(ValueError, match="exactly its own version"):
        bundle.merge(None, "2026.11", current)


def uploads(directory: Path, version: str) -> list[Upload]:
    index = json.loads((directory / "index.json").read_text())
    entries = [
        Upload(
            directory / record["url"],
            f"packs/{version}/{record['url']}",
            record["size"],
            record["sha256"],
        )
        for record in index["datasets"][version]["packs"].values()
    ]
    path = directory / "index.json"
    return [
        *entries,
        Upload(
            path, f"packs/{version}/index.json", path.stat().st_size, sha256_file(path)
        ),
    ]


def test_publication_maintains_the_aggregate_index(tmp_path: Path) -> None:
    destination = f"memory://aggregate-{uuid4()}"
    fs, base = fsspec.core.url_to_fs(destination)
    settings = PublishSettings()
    first = release(tmp_path / "a", "2026.10")
    preview = publish(
        uploads(first, "2026.10"), destination, "2026.10", settings, dry_run=True
    )
    assert preview["aggregate_index"] == "created"
    assert not fs.exists(base + "/packs/index.json")
    result = publish(
        uploads(first, "2026.10"), destination, "2026.10", settings, dry_run=False
    )
    assert result["aggregate_index"] == "created"
    second = release(tmp_path / "b", "2026.11")
    result = publish(
        uploads(second, "2026.11"), destination, "2026.11", settings, dry_run=False
    )
    assert result["aggregate_index"] == "updated"
    repeat = publish(
        uploads(first, "2026.10"), destination, "2026.10", settings, dry_run=False
    )
    assert repeat["aggregate_index"] == "unchanged"
    with fs.open(base + "/packs/index.json", "rb") as stream:
        value = json.loads(stream.read())
    assert sorted(value["datasets"]) == ["2026.10", "2026.11"]
    for version, dataset in value["datasets"].items():
        for pack in dataset["packs"].values():
            assert pack["url"].startswith(f"{version}/")
            assert fs.size(f"{base}/packs/{pack['url']}") == pack["size"]
