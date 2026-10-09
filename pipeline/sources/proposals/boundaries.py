"""Resolve geoBoundaries layers, catalog identity conflicts and immutable commits."""

import re
from typing import Any

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin
from pipeline.runtime.jsonio import digest

from .catalog import load
from .http import Client
from .resolve import finish


def country_reference(body: bytes, extra: dict[str, Any]) -> dict[str, Any]:
    result = dict(extra)
    for line in body.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 8:
            raise ValueError("Truncated GeoNames country reference row")
        result[fields[1]] = {
            "alpha2": fields[0],
            "population": int(fields[7]),
            "name": fields[4],
        }
    return result


def layers(client: Client, settings: dict[str, Any]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for selection in settings["layers"]:
        country, level = str(selection).split("/")
        payload = client.json(f"{settings['api']}/{country}/{level}/")
        for layer in payload if isinstance(payload, list) else [payload]:
            if layer.get("boundaryType") != level or not layer.get("boundaryISO"):
                raise ValueError("Unexpected country or level in boundary catalog")
            identity = str(layer["boundaryID"])
            actual_country, actual_level, _ = identity.split("-", 2)
            if (
                actual_country != layer["boundaryISO"]
                or actual_level != layer["boundaryType"]
            ):
                layer = client.json(
                    f"{settings['api']}/{actual_country}/{actual_level}/"
                )
            if (
                layer["boundaryISO"] != actual_country
                or layer["boundaryType"] != actual_level
                or not str(layer["boundaryID"]).startswith(
                    f"{actual_country}-{actual_level}-"
                )
            ):
                raise ValueError("Country API has inconsistent layer identity")
            key = f"{actual_country}-{actual_level}"
            if key in selected and selected[key] != layer:
                raise ValueError(f"Conflicting geoBoundaries layers: {key}")
            selected[key] = layer
    return [selected[key] for key in sorted(selected)]


def propose(settings: SourceSettings) -> SourcePin:
    client = Client(settings)
    catalog = load(settings).settings
    reference, reference_sha256 = client.document(str(catalog["country_reference"]))
    countries = country_reference(reference, catalog.get("extra_countries", {}))
    selected = layers(client, catalog)
    commits: dict[str, str] = {}
    payloads = []
    for layer in selected:
        url = str(layer["staticDownloadLink"])
        prefix = str(catalog["raw_prefix"])
        if not url.startswith(prefix):
            raise ValueError(f"Unexpected geoBoundaries layer URL: {url}")
        short, suffix = url.removeprefix(prefix).split("/", 1)
        if not re.fullmatch(r"[0-9a-f]{7,40}", short):
            raise ValueError("Layer URL does not bind a git commit")
        if short not in commits:
            commit = str(
                client.json(f"{catalog['repository_api']}/commits/{short}")["sha"]
            )
            if not re.fullmatch(r"[0-9a-f]{40}", commit) or not commit.startswith(
                short
            ):
                raise ValueError("Layer commit did not resolve to a matching full SHA")
            commits[short] = commit
        commit = commits[short]
        key = f"{layer['boundaryISO']}-{layer['boundaryType']}"
        metadata = {
            "key": key,
            "commit": commit,
            "metadata": layer,
            "original_url": url,
            "license": layer["boundaryLicense"],
            "license_url": layer.get("licenseSource", ""),
            "attribution": "geoBoundaries; " + layer["boundarySource"],
        }
        pin = client.pin(
            f"{commit}/{key}.zip", f"{catalog['media']}/{commit}/{suffix}", metadata
        )
        # Git LFS serves the object id, which is the SHA256 of the payload.
        if pin.etag != f'"{pin.sha256}"':
            raise ValueError(f"geoBoundaries LFS object id differs from SHA256: {key}")
        payloads.append(pin)
    return finish(
        payloads,
        "gbOpen-" + digest({"layers": selected})[:20],
        {
            "country_reference": countries,
            "country_reference_sha256": reference_sha256,
            "commits": {
                pin.metadata["key"]: pin.metadata["commit"] for pin in payloads
            },
        },
    )
