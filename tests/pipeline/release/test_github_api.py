"""The GitHub client paginates, streams, and sends its token only to GitHub's API."""

import hashlib
from pathlib import Path

import pytest

from pipeline.config.publication import GithubSettings
from pipeline.release.github_api import Client, GithubError, safe_hop
from tests.tools.github_fake import FakeGithub, running


def client(fake: FakeGithub, token: str | None = None) -> Client:
    settings = GithubSettings(
        repository=fake.repository,
        api_url=fake.api_url,
        upload_url=fake.upload_url,
        web_url=fake.web_url,
        timeout_seconds=10,
    )
    return Client(settings, fake.token if token is None else token, read_bytes=1024)


def test_drafts_are_listed_across_pages() -> None:
    with running(FakeGithub(page_size=2)) as fake:
        api = client(fake)
        for month in range(1, 6):
            api.create_release({"tag_name": f"v2026.{month}", "draft": True})
        releases = api.releases()
        assert sorted(r["tag_name"] for r in releases) == [
            f"v2026.{m}" for m in range(1, 6)
        ]
        assert all(r["draft"] for r in releases)
        pages = [r for r in fake.requests if r.method == "GET"]
        assert len(pages) == 3


def test_uploads_stream_and_downloads_drop_the_token(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 40
    path = tmp_path / "core.tar.zst"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    with running() as fake:
        api = client(fake)
        release = api.create_release({"tag_name": "v2026.10", "draft": True})
        asset = api.upload(release["id"], "core.tar.zst", path)
        assert (asset["state"], asset["size"]) == ("uploaded", len(payload))
        assert asset["digest"] == f"sha256:{digest}"
        assert api.download(asset["id"]) == (len(payload), digest)
        assert [a["id"] for a in api.assets(release["id"])] == [asset["id"]]
        api.delete_asset(asset["id"])
        assert api.assets(release["id"]) == []
        by_server = {(r.server, r.authorized) for r in fake.requests}
        assert ("objects", False) in by_server
        assert ("objects", True) not in by_server
        assert all(r.authorized for r in fake.requests if r.server != "objects")


def test_failures_name_the_request_but_never_the_token() -> None:
    with running() as fake:
        with pytest.raises(GithubError) as caught:
            client(fake).release(999)
        assert caught.value.status == 404
        assert "/releases/999" in str(caught.value)
        assert fake.token not in str(caught.value)
        with pytest.raises(GithubError, match="401"):
            client(fake, token="wrong").releases()


def test_an_interrupted_upload_leaves_an_incomplete_asset(tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    path.write_bytes(b"x" * 200_000)
    with running(FakeGithub(fail_upload_after=1000)) as fake:
        api = client(fake)
        release = api.create_release({"tag_name": "v2026.10", "draft": True})
        with pytest.raises(GithubError, match="interrupted"):
            api.upload(release["id"], "big.bin", path)
        assert [a["state"] for a in api.assets(release["id"])] == ["starter"]


def test_a_token_is_required() -> None:
    with pytest.raises(GithubError, match="GITHUB_TOKEN"):
        Client(GithubSettings(), "")


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("https://api.github.com/a", "https://objects.example/x", True),
        ("https://api.github.com/a", "http://objects.example/x", False),
        ("http://127.0.0.1:1/a", "http://127.0.0.1:2/x", True),
        ("http://127.0.0.1:1/a", "http://objects.example/x", False),
        ("https://api.github.com/a", "https://user@objects.example/x", False),
    ],
)
def test_redirects_never_downgrade(current: str, target: str, allowed: bool) -> None:
    if allowed:
        safe_hop(current, target)
    else:
        with pytest.raises(GithubError, match="Refusing"):
            safe_hop(current, target)
