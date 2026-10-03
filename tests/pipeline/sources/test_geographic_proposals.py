"""Paginated spatial upstreams and reviewed plate evidence, using loopback HTTP."""

import hashlib
import importlib
import json
from pathlib import Path
from typing import cast
from urllib.parse import urlencode

import pytest
import yaml

from pipeline.sources import policy
from pipeline.sources.contract import Source

from .proposal_server import Reply, publisher
from .test_proposals import settings


def listing(prefix: str, *, delimiter: str = "", continuation: str = "") -> str:
    params = {"list-type": "2", "prefix": prefix}
    if delimiter:
        params["delimiter"] = delimiter
    if continuation:
        params["continuation-token"] = continuation
    return "/?" + urlencode(params)


def test_overture_lists_latest_and_every_page_with_object_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        server.routes[listing("release/", delimiter="/")] = Reply(
            b"<ListBucketResult><CommonPrefixes><Prefix>release/2026-09-23.1/</Prefix></CommonPrefixes><CommonPrefixes><Prefix>release/2026-09-23.10/</Prefix></CommonPrefixes></ListBucketResult>"
        )
        prefix = "release/2026-09-23.10/theme=divisions/type=division/"
        for number, continuation in [(1, ""), (2, "next")]:
            key = prefix + f"part-{number}.parquet"
            body = f"PAR1{number}PAR1".encode()
            etag = '"' + hashlib.sha256(body).hexdigest() + '"'
            server.routes["/" + key] = Reply(body)
            xml = (
                f"<ListBucketResult><Contents><Key>{key}</Key>"
                f"<Size>{len(body)}</Size><ETag>{etag}</ETag></Contents>"
                f"<IsTruncated>{str(number == 1).lower()}</IsTruncated>"
            )
            if number == 1:
                xml += "<NextContinuationToken>next</NextContinuationToken>"
            server.routes[listing(prefix, continuation=continuation)] = Reply(
                (xml + "</ListBucketResult>").encode()
            )
        source = settings(
            tmp_path,
            monkeypatch,
            "overture",
            {
                "settings": {
                    "endpoint": server.url + "/",
                    "release_prefix": "release/",
                    "theme": "divisions",
                    "types": ["division"],
                }
            },
        )
        adapter = cast(Source, importlib.import_module(source.adapter))
        pin = adapter.propose(source)
        assert pin.release == "2026-09-23.10"
        assert len(pin.files) == 2 and all(
            f.metadata["type"] == "division" for f in pin.files
        )
        server.routes[listing(prefix, continuation="next")] = Reply(
            b"<ListBucketResult><IsTruncated>true</IsTruncated><NextContinuationToken>next</NextContinuationToken></ListBucketResult>"
        )
        with pytest.raises(ValueError, match="continuation token"):
            adapter.propose(source)


def test_geoboundaries_repairs_identity_and_pins_full_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        commit = "a" * 40
        layer = {
            "boundaryISO": "MYS",
            "boundaryType": "ADM0",
            "boundaryID": "MYS-ADM0-published",
            "staticDownloadLink": server.url + "/raw/aaaaaaa/layer.zip",
            "boundaryLicense": "CC-BY-4.0",
            "boundarySource": "Fixture publisher",
            "licenseSource": "https://example.test/licence",
        }
        broken = {**layer, "boundaryType": "ADM1"}
        server.routes.update(
            {
                "/countries": Reply(
                    b"MY\tMYS\t458\tMY\tMalaysia\tKuala Lumpur\t1\t30000000\n"
                ),
                "/api/ALL/ADM1/": Reply(json.dumps([broken]).encode()),
                "/api/MYS/ADM0/": Reply(json.dumps(layer).encode()),
                "/repo/commits/aaaaaaa": Reply(json.dumps({"sha": commit}).encode()),
                f"/media/{commit}/layer.zip": Reply(b"ZIP fixture"),
            }
        )
        source = settings(
            tmp_path,
            monkeypatch,
            "geoboundaries",
            {
                "settings": {
                    "api": server.url + "/api",
                    "layers": ["ALL/ADM1"],
                    "country_reference": server.url + "/countries",
                    "repository_api": server.url + "/repo",
                    "raw_prefix": server.url + "/raw/",
                    "media": server.url + "/media",
                }
            },
        )
        adapter = cast(Source, importlib.import_module(source.adapter))
        pin = adapter.propose(source)
        assert pin.files[0].name == commit + "/MYS-ADM0.zip"
        assert pin.files[0].metadata["metadata"] == layer
        assert pin.metadata["country_reference"]["MYS"]["alpha2"] == "MY"
        assert pin.metadata["commits"] == {"MYS-ADM0": commit}
        server.routes["/repo/commits/aaaaaaa"] = Reply(
            json.dumps({"sha": "b" * 40}).encode()
        )
        with pytest.raises(ValueError, match="matching full SHA"):
            adapter.propose(source)


def test_plate_proposal_uses_reviewed_urls_and_preserves_licences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with publisher() as server:
        server.routes["/reference"] = Reply(b"authority statement")
        source = settings(tmp_path, monkeypatch, "plates", {})
        monkeypatch.setattr(policy, "REPOSITORY", tmp_path)
        source.policies = {"sources": "evidence.yaml"}
        (tmp_path / "evidence.yaml").write_text(
            yaml.safe_dump(
                {
                    "reference.html": {
                        "url": server.url + "/reference",
                        "license": "OGL-UK-3.0",
                        "attribution": "Crown copyright",
                        "kind": "reference",
                        "sha256": "obsolete",
                    }
                }
            )
        )
        adapter = cast(Source, importlib.import_module(source.adapter))
        pin = adapter.propose(source)
        assert pin.files[0].metadata["license"] == "OGL-UK-3.0"
        assert pin.files[0].metadata["kind"] == "reference"
        assert pin.files[0].sha256 != "obsolete"
