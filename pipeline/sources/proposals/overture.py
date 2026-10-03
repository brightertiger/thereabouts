"""Resolve the latest complete Overture release and all configured division shards."""

import re
from collections.abc import Iterator
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin

from .catalog import load
from .http import Client
from .resolve import finish


def pages(
    client: Client, endpoint: str, parameters: dict[str, str]
) -> Iterator[ET.Element]:
    continuation = ""
    seen = set()
    while True:
        query = {"list-type": "2", **parameters}
        if continuation:
            query["continuation-token"] = continuation
        page = ET.fromstring(client.read(endpoint + "?" + urlencode(query)))
        yield page
        if page.findtext("{*}IsTruncated", "false") == "false":
            return
        continuation = page.findtext("{*}NextContinuationToken", "")
        if not continuation or continuation in seen:
            raise ValueError("Invalid continuation token in Overture listing")
        seen.add(continuation)


def propose(settings: SourceSettings) -> SourcePin:
    client = Client(settings)
    catalog = load(settings).settings
    endpoint = str(catalog["endpoint"])
    prefix = str(catalog["release_prefix"])
    releases = []
    for page in pages(client, endpoint, {"prefix": prefix, "delimiter": "/"}):
        for item in page.findall("{*}CommonPrefixes/{*}Prefix"):
            name = (item.text or "").removeprefix(prefix).rstrip("/")
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", name):
                releases.append(name)
    if not releases:
        raise ValueError("No Overture releases in upstream listing")
    release = max(releases, key=lambda value: tuple(map(int, re.split(r"[-.]", value))))
    payloads = []
    for kind in catalog["types"]:
        object_prefix = f"{prefix}{release}/theme={catalog['theme']}/type={kind}/"
        found = False
        for page in pages(client, endpoint, {"prefix": object_prefix}):
            for item in page.findall("{*}Contents"):
                key = item.findtext("{*}Key", "")
                if not key.startswith(object_prefix) or not key.endswith(".parquet"):
                    continue
                name = f"{release}/{kind}/{key.removeprefix(object_prefix)}"
                pin = client.pin(
                    name,
                    endpoint.rstrip("/") + "/" + key,
                    {
                        "key": key,
                        "type": kind,
                        "listed_last_modified": item.findtext("{*}LastModified"),
                        "license": settings.licence.id,
                        "license_url": settings.licence.url,
                        "attribution": settings.licence.attribution,
                    },
                )
                if pin.size != int(
                    item.findtext("{*}Size", "-1")
                ) or pin.etag != item.findtext("{*}ETag"):
                    raise ValueError(f"Overture object changed since listing: {key}")
                payloads.append(pin)
                found = True
        if not found:
            raise ValueError(f"Incomplete Overture release: no {kind} shards")
    return finish(payloads, release, {"objects": len(payloads)})
