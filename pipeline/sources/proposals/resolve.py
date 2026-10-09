"""Resolve configured releases, files and complete GitHub trees into proposals."""

import re
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.jsonio import digest

from .catalog import Catalog, File, load
from .http import Client


def expand(value: Any, variables: dict[str, str]) -> Any:
    if isinstance(value, str):
        return value.format_map(variables)
    if isinstance(value, dict):
        return {key: expand(item, variables) for key, item in value.items()}
    if isinstance(value, list):
        return [expand(item, variables) for item in value]
    return value


def variables(client: Client, catalog: Catalog) -> dict[str, str]:
    result = {"month": client.clock().strftime("%Y-%m")}
    for selector in catalog.selectors:
        url = selector.url.format_map(result)
        if selector.kind == "text":
            value = client.read(url).decode().strip()
        else:
            payload = client.json(url)
            key = "sha" if selector.kind == "github_commit" else "tag_name"
            value = str(payload[key])
            if selector.kind == "github_commit" and not re.fullmatch(
                r"[0-9a-f]{40}", value
            ):
                raise ValueError(f"Git commit is not a full immutable SHA: {url}")
        if not value or any(char in value for char in "\r\n/\\"):
            raise ValueError(f"Invalid upstream release identifier: {url}")
        if selector.name in result:
            raise ValueError(f"Duplicate release selector: {selector.name}")
        result[selector.name] = value
    return result


def files(client: Client, catalog: Catalog, values: dict[str, str]) -> list[PinFile]:
    candidates = list(catalog.files)
    for tree in catalog.trees:
        payload = client.json(tree.url.format_map(values))
        if payload.get("truncated"):
            raise ValueError("Incomplete upstream git tree; refuse partial proposal")
        for item in payload["tree"]:
            path = str(item["path"])
            if item["type"] == "blob" and (
                path in tree.names
                or any(path.startswith(prefix) for prefix in tree.prefixes)
            ):
                candidates.append(
                    File(
                        path,
                        tree.raw + path,
                        {**tree.metadata, "key": path, "git_blob": item["sha"]},
                    )
                )
    result = []
    for item in candidates:
        name = item.name.format_map(values)
        metadata = {
            "license": client.settings.licence.id,
            "license_url": client.settings.licence.url,
            "attribution": client.settings.licence.attribution,
            "key": name,
            **expand(item.metadata, values),
        }
        result.append(client.pin(name, item.url.format_map(values), metadata))
    return result


def finish(
    files: list[PinFile], release: str = "", metadata: dict[str, Any] | None = None
) -> SourcePin:
    if not files:
        raise ValueError(
            "No upstream payloads selected; configure reviewed evidence URLs first"
        )
    files.sort(key=lambda item: item.name)
    fingerprint = digest([asdict(item) for item in files])
    result = SourcePin(
        release or fingerprint,
        datetime.now(UTC).isoformat(),
        files=files,
        metadata={"inventory_fingerprint": fingerprint, **(metadata or {})},
    )
    result.validate()
    return result


def propose(settings: SourceSettings) -> SourcePin:
    client = Client(settings)
    catalog = load(settings)
    values = variables(client, catalog)
    return finish(
        files(client, catalog, values),
        catalog.release.format_map(values),
        {"releases": {key: value for key, value in values.items() if key != "month"}},
    )
