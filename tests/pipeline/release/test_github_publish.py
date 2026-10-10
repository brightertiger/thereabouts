"""GitHub publication: offline plan, draft first, resumable, then immutable."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from pipeline.release import github
from tests.tools.github_fake import Asset, FakeGithub, running

from .github_release import Built, build, settings

VERSION = "2026.10"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    return build(tmp_path_factory.mktemp("release"))


def publish_to(
    fake: FakeGithub,
    release: Built,
    work: Path,
    monkeypatch: pytest.MonkeyPatch,
    **changes: object,
) -> dict[str, Any]:
    monkeypatch.setenv("GITHUB_TOKEN", fake.token)
    return github.publish(
        release.entries(),
        release.dataset,
        release.version,
        settings(release.config, fake, **changes),
        dry_run=False,
        work=work,
    )


def expected_names(release: Built) -> set[str]:
    manifest = json.loads((release.dataset / "manifest.json").read_text())
    tables = {r["path"].split("/")[0] for r in manifest["files"] if "/" in r["path"]}
    documents = {r["path"] for r in manifest["files"] if "/" not in r["path"]}
    packs = {f"{f}.tar.zst" for f in release.packs} | {
        f"acceptance-{f}.json" for f in release.packs
    }
    return (
        packs
        | documents
        | {"manifest.json", "dataset-manifest.json", "index.json"}
        | {f"dataset-{t}.zip" for t in tables}
    )


def test_a_dry_run_plans_every_asset_offline(
    built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = github.publish(
        built.entries(),
        built.dataset,
        VERSION,
        built.config.release.publish,
        dry_run=True,
        work=tmp_path / "work",
    )
    names = {a["name"] for a in result["assets"]} | set(result["generated"])
    assert names == expected_names(built)
    assert (result["tag"], result["repository"]) == (
        "v2026.10",
        "brightertiger/thereabouts",
    )
    assert result["count"] == len(names) and result["unresolved"] == []
    assert not (tmp_path / "work").exists()


def test_a_release_is_published_with_absolute_urls_and_asset_ids(
    built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running(FakeGithub(private=False)) as fake:
        result = publish_to(fake, built, tmp_path / "work", monkeypatch)
        release = fake.published("v2026.10")
        assert release is not None and fake.latest == release.id
        assert result["state"] == "published" and result["skip"] == 0
        assets = {a.name: a for a in release.assets}
        assert set(assets) == expected_names(built)
        for entry in built.entries():
            name = entry.remote.rpartition("/")[2]
            if entry.remote.startswith("packs/") and "/acceptance/" in entry.remote:
                name = f"acceptance-{name}"
            uploaded = name != "index.json" and entry.remote.count("/") == 2
            if uploaded or "/acceptance/" in entry.remote:
                assert hashlib.sha256(assets[name].data).hexdigest() == entry.sha256
        index = json.loads(assets["index.json"].data)
        assert index["format"] == 3 and list(index["datasets"]) == [VERSION]
        entry = index["datasets"][VERSION]
        repo = fake.repository
        for family in built.packs:
            pack = entry["packs"][family]
            asset = assets[f"{family}.tar.zst"]
            assert pack["url"] == (
                f"{fake.web_url}/{repo}/releases/download/v2026.10/{family}.tar.zst"
            )
            assert pack["asset_id"] == asset.id
            assert pack["api_url"] == (
                f"{fake.api_url}/repos/{repo}/releases/assets/{asset.id}"
            )
            assert pack["sha256"] == hashlib.sha256(asset.data).hexdigest()
        described = assets["dataset-manifest.json"]
        assert entry["dataset"]["asset_id"] == described.id
        assert entry["dataset"]["sha256"] == hashlib.sha256(described.data).hexdigest()
        manifest = json.loads(described.data)
        files = {f["path"] for a in manifest["archives"] for f in a["files"]}
        files |= {f["path"] for f in manifest["files"]}
        recorded = json.loads((built.dataset / "manifest.json").read_text())["files"]
        assert files == {r["path"] for r in recorded} | {"manifest.json"}
        for archive in manifest["archives"]:
            data = assets[archive["name"]].data
            assert (len(data), hashlib.sha256(data).hexdigest()) == (
                archive["size"],
                archive["sha256"],
            )
        assert not any(r.authorized for r in fake.requests if r.server == "objects")
        again = publish_to(fake, built, tmp_path / "again", monkeypatch)
        assert (again["state"], again["upload"]) == ("published", 0)


def test_an_interrupted_upload_resumes_without_reuploading(
    built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeGithub(fail_upload_name="dataset-cells.zip", fail_upload_after=10)
    with running(fake):
        with pytest.raises(ValueError, match="rerun to resume"):
            publish_to(fake, built, tmp_path / "work", monkeypatch)
        (draft,) = fake.by_tag("v2026.10")
        assert draft.draft and fake.latest is None
        states = {a.name: a.state for a in draft.assets}
        assert states["dataset-cells.zip"] == "starter"
        result = publish_to(fake, built, tmp_path / "work", monkeypatch)
        assert result["deleted_incomplete"] == ["dataset-cells.zip"]
        assert result["state"] == "published"
        uploads = Counter(
            r.path.partition("?name=")[2]
            for r in fake.requests
            if r.server == "uploads"
        )
        assert uploads.pop("dataset-cells.zip") == 2
        assert set(uploads.values()) == {1}


def test_a_published_release_only_gains_missing_assets(
    built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running() as fake:
        publish_to(fake, built, tmp_path / "work", monkeypatch)
        release = fake.published("v2026.10")
        assert release is not None
        release.assets = [
            a for a in release.assets if a.name != "acceptance-phone.json"
        ]
        result = publish_to(fake, built, tmp_path / "work", monkeypatch)
        assert (result["state"], result["upload"]) == ("published", 1)
        readme = next(a for a in release.assets if a.name == "README.md")
        release.assets.remove(readme)
        with pytest.raises(ValueError, match="cannot be repaired in place"):
            publish_to(fake, built, tmp_path / "work", monkeypatch)
        assert not any(a.name == "README.md" for a in release.assets)
        release.assets.append(readme)
        phone = next(a for a in release.assets if a.name == "phone.tar.zst")
        phone.data = b"tampered"
        with pytest.raises(ValueError, match=r"Conflicting asset phone\.tar\.zst"):
            publish_to(fake, built, tmp_path / "work", monkeypatch)
        release.assets.append(Asset(1, "extra.txt", b"x"))
        with pytest.raises(ValueError, match=r"Unexpected asset extra\.txt"):
            publish_to(fake, built, tmp_path / "work", monkeypatch)


def test_owner_decisions_block_publication_and_private_stops_at_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = build(tmp_path / "release", contact="OWNER DECISION: public contact")
    with running() as fake:
        with pytest.raises(ValueError, match="OWNER DECISION text must be resolved"):
            publish_to(fake, held, tmp_path / "work", monkeypatch)
        assert fake.requests == []
        result = publish_to(fake, held, tmp_path / "work", monkeypatch, private=True)
        assert result["state"] == "draft"
        assert "dataset/2026.10/DATASET_CARD.md" in result["unresolved"]
        (draft,) = fake.by_tag("v2026.10")
        assert draft.draft and fake.latest is None and not fake.tags
        # Resolving the decision changes the documents: the old draft must go.
        resolved = build(tmp_path / "resolved")
        with pytest.raises(ValueError, match="delete the draft on GitHub and rerun"):
            publish_to(fake, resolved, tmp_path / "work", monkeypatch)
        fake.releases.pop(draft.id)
        result = publish_to(fake, resolved, tmp_path / "work", monkeypatch)
        assert result["state"] == "published"


def test_limits_and_the_token_are_checked_before_any_request(
    built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running() as fake:
        work = tmp_path / "work"
        with pytest.raises(ValueError, match="GitHub allows 5"):
            publish_to(fake, built, work, monkeypatch, github_max_assets=5)
        with pytest.raises(ValueError, match="one release asset"):
            publish_to(fake, built, work, monkeypatch, github_max_asset_bytes=1000)
        monkeypatch.delenv("GITHUB_TOKEN")
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            github.publish(
                built.entries(),
                built.dataset,
                VERSION,
                settings(built.config, fake),
                dry_run=False,
                work=work,
            )
        assert fake.requests == []


def test_assets_without_digests_are_downloaded_and_hashed(
    built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running(FakeGithub(digests=False)) as fake:
        result = publish_to(fake, built, tmp_path / "work", monkeypatch)
        downloads = [r for r in fake.requests if r.server == "objects"]
        assert result["state"] == "published"
        assert len(downloads) == result["upload"]
        assert not any(r.authorized for r in downloads)


def test_each_release_index_lists_every_published_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    versions = ("2026.10", "2026.11", "2026.09")
    releases = {
        v: build(tmp_path / v, version=v, families=("phone",)) for v in versions
    }
    with running() as fake:
        for version in versions:
            publish_to(
                fake, releases[version], tmp_path / "work" / version, monkeypatch
            )
        latest = fake.releases[fake.latest or 0]
        assert latest.tag_name == "v2026.11"

        def listed(tag: str) -> list[str]:
            release = fake.published(tag)
            assert release is not None
            index = next(a for a in release.assets if a.name == "index.json")
            return sorted(json.loads(index.data)["datasets"])

        assert listed("v2026.10") == ["2026.10"]
        assert listed("v2026.11") == ["2026.10", "2026.11"]
        assert listed("v2026.09") == ["2026.09", "2026.10", "2026.11"]
        # Rerunning an older release keeps its index: it lists its own version exactly.
        again = publish_to(
            fake, releases["2026.10"], tmp_path / "work" / "2026.10", monkeypatch
        )
        assert (again["upload"], again["aggregate_index"]) == (0, "kept")


def test_a_draft_index_gains_versions_published_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    releases = {
        v: build(tmp_path / v, version=v, families=("phone",))
        for v in ("2026.10", "2026.11")
    }
    with running() as fake:
        work = tmp_path / "work"
        draft = publish_to(
            fake, releases["2026.11"], work / "2026.11", monkeypatch, private=True
        )
        assert draft["state"] == "draft"
        publish_to(fake, releases["2026.10"], work / "2026.10", monkeypatch)
        result = publish_to(fake, releases["2026.11"], work / "2026.11", monkeypatch)
        assert (result["state"], result["aggregate_index"]) == ("published", "replaced")
        latest = fake.releases[fake.latest or 0]
        assert latest.tag_name == "v2026.11"
        index = next(a for a in latest.assets if a.name == "index.json")
        assert sorted(json.loads(index.data)["datasets"]) == ["2026.10", "2026.11"]
