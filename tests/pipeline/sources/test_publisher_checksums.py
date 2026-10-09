"""Publisher checksums are verified wherever a publisher provides one."""

import gzip
import hashlib
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from pipeline.pins.evidence import verify_publisher
from pipeline.runtime.ledger import Ledger
from pipeline.sources.contract import Proposer
from pipeline.sources.download import download
from pipeline.sources.proposals.http import Client

from .proposal_server import Reply, publisher
from .test_download_objects import pinned, source, upload
from .test_proposals import settings

CSV = b'"1.0.0.0","1.0.0.255","AU","Queensland","South Brisbane","-27.4","153.0"\n'
ARCHIVE = gzip.compress(CSV, mtime=0)


@pytest.mark.parametrize(
    "metadata,valid",
    [
        ({}, True),
        ({"publisher_md5": hashlib.md5(ARCHIVE).hexdigest()}, True),
        ({"publisher_md5": hashlib.md5(CSV).hexdigest()}, False),
        (
            {
                "publisher_md5": hashlib.md5(CSV).hexdigest(),
                "publisher_md5_covers": "decompressed",
            },
            True,
        ),
        ({"publisher_md5": "0" * 32, "publisher_md5_covers": "decompressed"}, False),
    ],
)
def test_publisher_md5_covers_the_file_or_its_decompressed_content(
    tmp_path: Path, metadata: dict[str, str], valid: bool
) -> None:
    path = tmp_path / "dbip.csv.gz"
    path.write_bytes(ARCHIVE)
    if valid:
        verify_publisher(path, metadata, 7, "dbip.csv.gz")
    else:
        with pytest.raises(ValueError, match="Publisher MD5 differs"):
            verify_publisher(path, metadata, 7, "dbip.csv.gz")


def test_dbip_proposal_carries_and_checks_reviewed_publisher_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "dbip-city-lite-2026-10.csv.gz"
    evidence = {
        "publisher_md5": hashlib.md5(CSV).hexdigest(),
        "publisher_md5_covers": "decompressed",
        "publisher_rows": 1,
    }
    with publisher() as server:
        source_settings = settings(
            tmp_path,
            monkeypatch,
            "dbip",
            {
                "release": "{month}",
                "files": [
                    {
                        "name": "dbip-city-lite-{month}.csv.gz",
                        "url": server.url + "/{month}",
                    }
                ],
                "settings": {"publisher": {name: evidence}},
            },
        )
        server.routes["/2026-10"] = Reply(ARCHIVE)
        october = datetime(2026, 10, 1, tzinfo=UTC)
        monkeypatch.setattr(Client, "now", lambda self: october)
        proposer = cast(Proposer, importlib.import_module(source_settings.proposer))
        pin = proposer.propose(source_settings)
        assert pin.release == "2026-10"
        assert {k: pin.files[0].metadata[k] for k in evidence} == evidence
        server.routes["/2026-10"] = Reply(gzip.compress(b"other\n", mtime=0))
        with pytest.raises(ValueError, match="Publisher MD5 differs"):
            proposer.propose(source_settings)


def test_download_refuses_bytes_that_contradict_the_publisher(tmp_path: Path) -> None:
    url = "memory://publisher-upstream/" + tmp_path.name + "/dbip.csv.gz"
    upload(url, ARCHIVE)
    with Ledger(tmp_path, None, readonly=False) as ledger:
        pin = pinned(url, ARCHIVE, "dbip.csv.gz")
        pin.metadata.update(publisher_md5="0" * 32, publisher_md5_covers="decompressed")
        with pytest.raises(ValueError, match="Publisher MD5 differs"):
            download(source(tmp_path, ledger, pin))
        pin.metadata["publisher_md5"] = hashlib.md5(CSV).hexdigest()
        assert download(source(tmp_path, ledger, pin))[0].read_bytes() == ARCHIVE


def test_geoboundaries_layer_must_be_served_under_its_lfs_object_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commit = "a" * 40
    layer = {
        "boundaryISO": "MYS",
        "boundaryType": "ADM0",
        "boundaryID": "MYS-ADM0-published",
        "boundaryLicense": "CC-BY-4.0",
        "boundarySource": "Fixture publisher",
        "licenseSource": "https://example.test/licence",
    }
    with publisher() as server:
        layer["staticDownloadLink"] = server.url + "/raw/aaaaaaa/layer.zip"
        server.routes.update(
            {
                "/countries": Reply(b"MY\tMYS\t458\tMY\tMalaysia\tKL\t1\t30000000\n"),
                "/api/MYS/ADM0/": Reply(json.dumps(layer).encode()),
                "/repo/commits/aaaaaaa": Reply(json.dumps({"sha": commit}).encode()),
                f"/media/{commit}/layer.zip": Reply(
                    b"ZIP fixture", headers={"ETag": '"not-the-object-id"'}
                ),
            }
        )
        source_settings = settings(
            tmp_path,
            monkeypatch,
            "geoboundaries",
            {
                "settings": {
                    "api": server.url + "/api",
                    "layers": ["MYS/ADM0"],
                    "country_reference": server.url + "/countries",
                    "repository_api": server.url + "/repo",
                    "raw_prefix": server.url + "/raw/",
                    "media": server.url + "/media",
                }
            },
        )
        proposer = cast(Proposer, importlib.import_module(source_settings.proposer))
        with pytest.raises(ValueError, match="LFS object id"):
            proposer.propose(source_settings)
        server.routes[f"/media/{commit}/layer.zip"] = Reply(b"ZIP fixture")
        pin = proposer.propose(source_settings)
    assert pin.files[0].etag == '"' + pin.files[0].sha256 + '"'
    assert (
        pin.metadata["country_reference_sha256"]
        == hashlib.sha256(b"MY\tMYS\t458\tMY\tMalaysia\tKL\t1\t30000000\n").hexdigest()
    )
