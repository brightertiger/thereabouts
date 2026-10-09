"""Upstream proposals use loopback publishers and never mutate the lock implicitly."""

import hashlib
import importlib
import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from pipeline.config import load
from pipeline.config.sources import SourceSettings, validate_source
from pipeline.errors import ConfigError
from pipeline.pins import cli
from pipeline.pins.lock import read_lock
from pipeline.sources.contract import Proposer
from pipeline.sources.proposals import catalog
from pipeline.sources.proposals.http import Client

from .proposal_server import Reply, publisher


def settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, spec: dict[str, Any]
) -> SourceSettings:
    monkeypatch.setattr(catalog, "REPOSITORY", tmp_path)
    (tmp_path / "proposal.yaml").write_text(yaml.safe_dump(spec))
    source = load().sources[name]
    source.upstream["proposal"] = "proposal.yaml"
    source.limits.download_bytes = 4096
    source.limits.retries = 0
    return source


@pytest.mark.parametrize(
    "name",
    [
        "airports",
        "codes",
        "dbip",
        "ghsl",
        "phone",
        "postal",
        "timezones",
        "unlocode",
        "plate_country",
    ],
)
def test_catalog_adapters_hash_publisher_bytes(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        server.routes["/payload"] = Reply(b"precise publisher payload")
        source = settings(
            tmp_path,
            monkeypatch,
            name,
            {
                "release": "fixture",
                "files": [{"name": "input", "url": server.url + "/payload"}],
            },
        )
        proposer = cast(Proposer, importlib.import_module(source.proposer))
        pin = proposer.propose(source)
        assert pin.release == "fixture"
        assert (
            pin.files[0].sha256
            == hashlib.sha256(b"precise publisher payload").hexdigest()
        )
        assert pin.files[0].size == len(b"precise publisher payload")
        assert pin.files[0].metadata["license"] == source.licence.id
        assert [r[0] for r in server.requests] == ["HEAD", "GET"]
        assert server.requests[-1][2]["If-Match"] == pin.files[0].etag


@pytest.mark.parametrize(
    "name,date_format,expected",
    [
        ("geonames", "%Y%m%d", "20261001"),
        ("osm_land", "%Y-%m-%dT%H:%M:%S%z", "2026-10-01T03:37:19+0000"),
    ],
)
def test_dump_date_is_publisher_evidence(
    name: str,
    date_format: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with publisher() as server:
        server.routes["/dump"] = Reply(b"dump")
        source = settings(
            tmp_path,
            monkeypatch,
            name,
            {
                "files": [{"name": "dump", "url": server.url + "/dump"}],
                "settings": {"release_file": "dump", "date_format": date_format},
            },
        )
        proposer = cast(Proposer, importlib.import_module(source.proposer))
        assert proposer.propose(source).release == expected


def test_latest_commit_release_and_complete_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        commit = "a" * 40
        server.routes.update(
            {
                "/commit": Reply(json.dumps({"sha": commit}).encode()),
                "/release": Reply(b'{"tag_name":"2026d"}'),
                "/iana": Reply(b"2026e\n"),
                f"/tree/{commit}": Reply(
                    b'{"truncated":false,"tree":[{"type":"blob","path":"keep/data","sha":"blob"},{"type":"blob","path":"ignore","sha":"other"}]}'
                ),
                f"/raw/{commit}/keep/data": Reply(b"tree payload"),
            }
        )
        source = settings(
            tmp_path,
            monkeypatch,
            "phone",
            {
                "release": "{commit}+{boundary}+{iana}",
                "selectors": [
                    {
                        "name": "commit",
                        "kind": "github_commit",
                        "url": server.url + "/commit",
                    },
                    {
                        "name": "boundary",
                        "kind": "github_release",
                        "url": server.url + "/release",
                    },
                    {"name": "iana", "kind": "text", "url": server.url + "/iana"},
                ],
                "trees": [
                    {
                        "url": server.url + "/tree/{commit}",
                        "raw": server.url + "/raw/{commit}/",
                        "prefixes": ["keep/"],
                    }
                ],
            },
        )
        proposer = cast(Proposer, importlib.import_module(source.proposer))
        result = proposer.propose(source)
        assert result.release == commit + "+2026d+2026e"
        assert [p.name for p in result.files] == ["keep/data"]
        server.routes[f"/tree/{commit}"] = Reply(b'{"truncated":true,"tree":[]}')
        with pytest.raises(ValueError, match="Incomplete upstream git tree"):
            proposer.propose(source)


def test_proposal_then_explicit_accept_and_unchanged_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        server.routes["/payload"] = Reply(b"stable")
        source = settings(
            tmp_path,
            monkeypatch,
            "airports",
            {"files": [{"name": "airports.csv", "url": server.url + "/payload"}]},
        )
        config = load()
        config.sources = {"airports": source}
        monkeypatch.setattr(cli, "load", lambda **_: config)
        lock, proposal = tmp_path / "pins.lock", tmp_path / "candidate.yaml"
        args = ["update", "--lock", str(lock), "--proposal", str(proposal)]
        assert cli.main([*args, "--root", str(tmp_path / "workspace")]) == 0
        assert not lock.exists()
        assert len(list((tmp_path / "workspace/raw/airports/sha256").iterdir())) == 1
        assert json.loads(proposal.with_suffix(".diff.json").read_bytes())["airports"][
            "added"
        ] == ["airports.csv"]
        count = len(server.requests)
        assert cli.main([*args, "--from-file", str(proposal), "--accept"]) == 0
        assert len(server.requests) == count
        before = lock.read_bytes()
        assert cli.main([*args, "--root", str(tmp_path / "workspace"), "--accept"]) == 0
        assert lock.read_bytes() == before
        assert read_lock(lock)["airports"].files[0].name == "airports.csv"


def test_changed_etag_and_oversized_payload_refuse_proposals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        source = settings(tmp_path, monkeypatch, "airports", {})
        server.routes["/payload"] = Reply(b"payload", get_headers={"ETag": '"changed"'})
        with pytest.raises(ValueError, match="changed during transfer"):
            Client(source).pin("input", server.url + "/payload", {})
        source.limits.download_bytes = 1
        server.requests.clear()
        with pytest.raises(ValueError, match="before download"):
            Client(source).pin("input", server.url + "/payload", {})
        assert [r[0] for r in server.requests] == ["HEAD"]


def test_every_source_names_its_proposer_in_yaml() -> None:
    for name, source in load().sources.items():
        assert source.proposer.startswith("pipeline.sources.proposals."), name
        proposer = cast(Proposer, importlib.import_module(source.proposer))
        assert callable(proposer.propose), name
        if name in {"plates", "plate_country"}:
            continue  # Their own wrappers remain until their package drops them.
        adapter = importlib.import_module(source.adapter)
        assert not hasattr(adapter, "propose") and not hasattr(adapter, "Options")


def test_a_proposer_outside_the_pipeline_is_rejected() -> None:
    source = load().sources["airports"]
    source.proposer = "os"
    with pytest.raises(ConfigError, match="Invalid source proposer"):
        validate_source(source)
