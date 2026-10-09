"""Replay a pin's upstream answers so the real proposers can run offline.

Only the transport is simulated: metadata documents (GitHub, geoBoundaries and
S3 listings) are rebuilt from the pin, and each payload reports the size,
SHA256 and validators the pin recorded. Resolution, naming, metadata and
release rules are the production code's.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from xml.sax.saxutils import escape

import pytest

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import PinFile, SourcePin
from pipeline.sources.proposals import http
from pipeline.sources.proposals.catalog import load
from pipeline.sources.proposals.http import Client, Head
from pipeline.storage.transfer import Received


@dataclass
class Replay:
    now: datetime
    payloads: dict[str, list[PinFile]] = field(default_factory=dict)
    documents: dict[str, bytes] = field(default_factory=dict)
    references: dict[str, str] = field(default_factory=dict)
    key: str = ""

    def payload(self, url: str) -> PinFile:
        # Wikipedia's parse API rendered one revision differently over time, so
        # plates pins one URL under several names; the logical key tells them apart.
        candidates = self.payloads[url]
        if len(candidates) > 1:
            candidates = [
                item
                for item in candidates
                if item.metadata.get("key", item.name) == self.key
            ]
        if len(candidates) != 1:
            raise AssertionError(f"No single pinned payload for {url} ({self.key})")
        return candidates[0]

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pin = Client.pin

        def named(
            client: Client, name: str, url: str, metadata: dict[str, Any]
        ) -> PinFile:
            self.key = str(metadata.get("key", name))
            return pin(client, name, url, metadata)

        def read(client: Client, url: str) -> bytes:
            if url not in self.documents:
                raise AssertionError(f"Unexpected upstream document: {url}")
            return self.documents[url]

        def document(client: Client, url: str) -> tuple[bytes, str]:
            return read(client, url), self.references[url]

        def head(client: Client, url: str) -> Head:
            item = self.payload(url)
            return Head(item.size, item.etag, item.last_modified)

        def store(
            client: Client, objects: Path, url: str, head: Head, limit: int
        ) -> Received:
            item = self.payload(url)
            return Received(item.size, item.sha256, "", False)

        monkeypatch.setattr(Client, "pin", named)
        monkeypatch.setattr(Client, "now", lambda client: self.now)
        monkeypatch.setattr(Client, "read", read)
        monkeypatch.setattr(Client, "document", document)
        monkeypatch.setattr(Client, "head", head)
        monkeypatch.setattr(Client, "store", store)
        # Publisher checksums need bytes; their checks are tested on real bytes.
        monkeypatch.setattr(http, "verify_publisher", lambda *args: None)


def replay(
    pin: SourcePin, settings: SourceSettings, facts: Mapping[str, Any]
) -> Replay:
    """Facts are the upstream release identifiers: selector values, the month,
    and for geoBoundaries the SHA256 of the country reference document."""
    month = str(facts["month"])
    result = Replay(datetime.strptime(month + "-15", "%Y-%m-%d").replace(tzinfo=UTC))
    for item in pin.files:
        result.payloads.setdefault(item.url, []).append(item)
    if settings.name == "geoboundaries":
        _boundaries(result, pin, settings, facts)
    elif settings.name == "overture":
        _listings(result, pin, settings)
    elif settings.upstream.get("proposal"):
        _catalog(result, pin, settings, facts)
    return result


def _json(value: object) -> bytes:
    return json.dumps(value).encode()


def _catalog(
    result: Replay, pin: SourcePin, settings: SourceSettings, facts: Mapping[str, Any]
) -> None:
    catalog = load(settings)
    values = {"month": str(facts["month"])}
    for selector in catalog.selectors:
        value = str(facts[selector.name])
        result.documents[selector.url.format_map(values)] = {
            "github_commit": _json({"sha": value}),
            "github_release": _json({"tag_name": value}),
            "text": (value + "\n").encode(),
        }[selector.kind]
        values[selector.name] = value
    for tree in catalog.trees:
        result.documents[tree.url.format_map(values)] = _json(
            {
                "truncated": False,
                "tree": [
                    {"type": "blob", "path": item.metadata["key"], "sha": blob}
                    for item in pin.files
                    if (blob := item.metadata.get("git_blob"))
                ],
            }
        )


def _boundaries(
    result: Replay, pin: SourcePin, settings: SourceSettings, facts: Mapping[str, Any]
) -> None:
    catalog = load(settings).settings
    reference = str(catalog["country_reference"])
    # countryInfo.txt columns: ISO, ISO3, ..., Country (5th), ..., Population (8th).
    result.documents[reference] = "".join(
        f"{entry['alpha2']}\t{alpha3}\t\t\t{entry['name']}\t\t\t{entry['population']}\n"
        for alpha3, entry in pin.metadata["country_reference"].items()
    ).encode()
    result.references[reference] = str(facts["country_reference_sha256"])
    layers = [item.metadata["metadata"] for item in pin.files]
    for selection in catalog["layers"]:
        country, level = str(selection).split("/")
        chosen = [
            layer
            for layer in layers
            if layer["boundaryType"] == level
            and country in ("ALL", layer["boundaryISO"])
        ]
        answer: object = chosen if country == "ALL" else chosen[0]
        result.documents[f"{catalog['api']}/{country}/{level}/"] = _json(answer)
    for item in pin.files:
        link = str(item.metadata["metadata"]["staticDownloadLink"])
        short = link.removeprefix(str(catalog["raw_prefix"])).split("/", 1)[0]
        result.documents[f"{catalog['repository_api']}/commits/{short}"] = _json(
            {"sha": item.metadata["commit"]}
        )


def _listings(result: Replay, pin: SourcePin, settings: SourceSettings) -> None:
    catalog = load(settings).settings
    endpoint, prefix = str(catalog["endpoint"]), str(catalog["release_prefix"])

    def listing(parameters: dict[str, str], body: str) -> None:
        query = urlencode({"list-type": "2", **parameters})
        result.documents[endpoint + "?" + query] = (
            f"<ListBucketResult>{body}<IsTruncated>false</IsTruncated>"
            "</ListBucketResult>"
        ).encode()

    listing(
        {"prefix": prefix, "delimiter": "/"},
        f"<CommonPrefixes><Prefix>{prefix}{pin.release}/</Prefix></CommonPrefixes>",
    )
    for kind in catalog["types"]:
        listing(
            {"prefix": f"{prefix}{pin.release}/theme={catalog['theme']}/type={kind}/"},
            "".join(
                f"<Contents><Key>{escape(item.metadata['key'])}</Key>"
                f"<LastModified>{item.metadata['listed_last_modified']}</LastModified>"
                f"<ETag>{escape(item.etag or '')}</ETag><Size>{item.size}</Size>"
                "</Contents>"
                for item in pin.files
                if item.metadata["type"] == kind
            ),
        )
