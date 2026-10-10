"""A release published to the loopback GitHub installs through the clients.

The pipeline publisher uploads the fixture release; the Python console (the Rust
CLI) and the Node CLI then install packs and restore the dataset, without a token
from a public release and with one from a private release. The token must reach
only the API; the object host must never see it.
"""

import os
import subprocess
from pathlib import Path

import pytest

from pipeline.release import github
from tests.client.hosts import NODE_CLIENT, node_available
from tests.pipeline.release.github_release import Built, build, settings
from tests.tools.github_fake import FakeGithub, running

from .helpers import CONSOLE

CLIENTS = ("python", "node")
SCRUBBED = ("THEREABOUTS_RELEASE_TOKEN", "GITHUB_TOKEN", "THEREABOUTS_GITHUB_API_URL")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Built:
    return build(tmp_path_factory.mktemp("release"))


def environment(**extra: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in SCRUBBED and "proxy" not in key.lower()
    }
    env["NO_PROXY"] = "*"
    env.update(extra)
    return env


def client(
    kind: str, root: Path, *args: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    command = (
        [str(CONSOLE)]
        if kind == "python"
        else [node_available(), str(NODE_CLIENT / "bin/thereabouts.js")]
    )
    return subprocess.run(
        [*command, "--data-dir", str(root), *args],
        text=True,
        capture_output=True,
        env=env,
        timeout=180,
        check=False,
    )


def publish(
    fake: FakeGithub, built: Built, work: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", fake.token)
    result = github.publish(
        built.entries(),
        built.dataset,
        built.version,
        settings(built.config, fake),
        dry_run=False,
        work=work,
    )
    monkeypatch.delenv("GITHUB_TOKEN")
    assert result["state"] == "published"
    fake.requests.clear()


def tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.parametrize("kind", CLIENTS)
def test_a_public_release_installs_packs_and_the_dataset(
    kind: str, built: Built, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with running(FakeGithub(private=False)) as fake:
        publish(fake, built, tmp_path / "work", monkeypatch)
        fake.cut_download_after, fake.cut_download_name = 1000, "core.tar.zst"
        env = environment(THEREABOUTS_RELEASE_URL=fake.release_url())
        store = tmp_path / "store"
        install = ("data", "install", "core", "phone", "--yes")
        first = client(kind, store, *install, env=env)
        assert first.returncode != 0 and "resume" in first.stderr, first.stderr
        second = client(kind, store, *install, env=env)
        assert second.returncode == 0, second.stderr
        ranges = [
            r.range
            for r in fake.requests
            if r.server == "objects" and "/core.tar.zst" in r.path
        ]
        assert ranges == [None, "bytes=1000-"]
        verified = client(kind, store, "data", "verify", "--full", env=env)
        assert verified.returncode == 0, verified.stderr
        dataset = client(kind, store, "data", "install", "dataset", env=env)
        assert dataset.returncode == 0, dataset.stderr
        assert tree(store / "dataset" / built.version) == tree(built.dataset)
        assert not any(r.authorized for r in fake.requests)
        assert not any(r.server == "api" for r in fake.requests)


@pytest.mark.parametrize(
    ("kind", "variable"),
    [("python", "THEREABOUTS_RELEASE_TOKEN"), ("node", "GITHUB_TOKEN")],
)
def test_a_private_release_needs_a_token_that_stays_at_the_api(
    kind: str,
    variable: str,
    built: Built,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with running(FakeGithub(private=True)) as fake:
        publish(fake, built, tmp_path / "work", monkeypatch)
        public = environment(THEREABOUTS_RELEASE_URL=fake.release_url())
        store = tmp_path / "store"
        refused = client(kind, store, "data", "install", "phone", env=public)
        assert refused.returncode != 0
        assert not (store / "packs").exists()
        token = {variable: fake.token, "THEREABOUTS_GITHUB_API_URL": fake.api_url}
        env = {**public, **token}
        installed = client(kind, store, "data", "install", "core", "phone", env=env)
        assert installed.returncode == 0, installed.stderr
        dataset = client(kind, store, "data", "install", "dataset", env=env)
        assert dataset.returncode == 0, dataset.stderr
        assert tree(store / "dataset" / built.version) == tree(built.dataset)
        assert fake.token not in installed.stdout + installed.stderr
        assert {r.server for r in fake.requests if r.authorized} == {"api"}
        assert all(r.authorized for r in fake.requests if r.server == "api")
        assert not any(r.authorized for r in fake.requests if r.server == "objects")
        assert len([r for r in fake.requests if r.server == "web"]) == 1
