"""Proposals keep the bytes they hash, so downloads never fetch them twice."""

import hashlib
import json
from pathlib import Path

import pytest

from pipeline.config import load
from pipeline.pins import cli
from pipeline.pins.lock import read_lock
from pipeline.pins.proposal import upstream
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.records import Recipe
from pipeline.sources.contract import SourceContext
from pipeline.sources.download import download
from pipeline.sources.proposals.http import Client, Custody, keeping
from pipeline.stages.contract import make_unit
from pipeline.storage.transfer import USER_AGENT

from ..helpers import context
from ..storage.flaky_server import Step, flaky
from .proposal_server import Reply, publisher
from .test_proposals import settings


def test_upstream_rewritten_after_proposal_downloads_the_kept_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, mirror = tmp_path / "workspace", tmp_path / "mirror"
    lock, proposal = tmp_path / "pins.lock", tmp_path / "candidate.yaml"
    with publisher() as server:
        server.routes["/airports.csv"] = Reply(b"ident,name\nPROPOSED,bytes\n")
        source = settings(
            tmp_path,
            monkeypatch,
            "airports",
            {"files": [{"name": "airports.csv", "url": server.url + "/airports.csv"}]},
        )
        config = load()
        config.sources = {"airports": source}
        config.storage = {"local": "file://", "gcs_raw": mirror.as_uri()}
        monkeypatch.setattr(cli, "load", lambda **_: config)
        arguments = ["update", "airports", "--root", str(workspace)]
        files = ["--lock", str(lock), "--proposal", str(proposal), "--accept"]
        assert cli.main([*arguments, *files]) == 0
        pin = read_lock(lock)["airports"]
        stored = workspace / "raw/airports/sha256" / pin.files[0].sha256
        assert stored.read_bytes() == b"ident,name\nPROPOSED,bytes\n"
        assert (mirror / "sha256" / pin.files[0].sha256).is_file()

        # Upstream overwrites the file in place (a nightly dump), after review.
        server.routes["/airports.csv"] = Reply(b"ident,name\nREWRITTEN,later\n")
        requests = len(server.requests)
        with Ledger(workspace, None, readonly=False) as ledger:
            ctx = context(workspace, ledger)
            ctx.storage = dict(config.storage)
            unit = make_unit(ctx, Recipe("download", "airports"), "fixture")
            target = SourceContext(ctx, source, pin, unit)
            assert download(target)[0] == stored
            stored.unlink()
            assert download(target)[0] == stored
        assert stored.read_bytes() == b"ident,name\nPROPOSED,bytes\n"
        assert len(server.requests) == requests


def test_interrupted_proposal_resumes_after_the_files_it_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        server.routes["/first"] = Reply(b"first payload")
        source = settings(
            tmp_path,
            monkeypatch,
            "postal",
            {
                "files": [
                    {"name": "first.zip", "url": server.url + "/first"},
                    {"name": "second.zip", "url": server.url + "/second"},
                ]
            },
        )
        custody = Custody(tmp_path / "workspace/raw")
        config = load()
        config.sources = {"postal": source}
        with pytest.raises(Exception, match="404"):
            upstream(config, ["postal"], custody)
        server.routes["/second"] = Reply(b"second payload")
        server.requests.clear()
        pin = upstream(config, ["postal"], custody)["postal"]
    assert [(method, path) for method, path, _ in server.requests] == [
        ("HEAD", "/first"),
        ("HEAD", "/second"),
        ("GET", "/second"),
    ]
    assert [item.sha256 for item in pin.files] == [
        hashlib.sha256(b"first payload").hexdigest(),
        hashlib.sha256(b"second payload").hexdigest(),
    ]
    progress = json.loads(
        (tmp_path / "workspace/raw/postal/proposal-progress.json").read_bytes()
    )
    assert sorted(progress) == [server.url + "/first", server.url + "/second"]


def test_changed_upstream_is_fetched_again_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        server.routes["/payload"] = Reply(b"version one")
        source = settings(tmp_path, monkeypatch, "airports", {})
        with keeping(Custody(tmp_path / "raw")):
            first = Client(source).pin("input", server.url + "/payload", {})
            server.routes["/payload"] = Reply(b"version two")
            second = Client(source).pin("input", server.url + "/payload", {})
    assert first.sha256 != second.sha256
    assert second.sha256 == hashlib.sha256(b"version two").hexdigest()
    assert (tmp_path / "raw/airports/sha256" / first.sha256).is_file()
    assert (tmp_path / "raw/airports/sha256" / second.sha256).is_file()


def test_short_proposal_body_is_resumed_and_identified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = bytes(range(256)) * 8
    source = settings(tmp_path, monkeypatch, "airports", {})
    source.limits.retries = 2
    source.limits.backoff_seconds = 0.0
    with flaky(body, [Step(cut=700)]) as server, keeping(Custody(tmp_path / "raw")):
        pin = Client(source).pin("input", server.url, {})
    assert pin.sha256 == hashlib.sha256(body).hexdigest()
    assert server.ranges() == [None, None, "bytes=700-"]
    assert [method for method, _ in server.requests] == ["HEAD", "GET", "GET"]
    assert all(headers["User-Agent"] == USER_AGENT for _, headers in server.requests)
    assert "github.com/brightertiger/thereabouts" in USER_AGENT
    assert not list((tmp_path / "raw/airports/sha256").glob("*.part"))


def test_upstream_proposal_requires_a_workspace(tmp_path: Path) -> None:
    lock = ["--lock", str(tmp_path / "pins.lock")]
    proposal = ["--proposal", str(tmp_path / "candidate.yaml")]
    with pytest.raises(ValueError, match="--root or --profile"):
        cli.main(["update", "airports", *lock, *proposal])
    with pytest.raises(ValueError, match="upstream proposals only"):
        cli.main(
            [
                "update",
                *lock,
                *proposal,
                "--root",
                str(tmp_path),
                "--from-file",
                str(tmp_path / "candidate.yaml"),
            ]
        )
    with pytest.raises(ValueError, match="require pins update"):
        cli.main(["check", *lock, "--root", str(tmp_path)])
