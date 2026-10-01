"""Geoboundaries inventory."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import Workspace, fingerprint
from .geoboundaries_config import ADM2_COUNTRIES, API, SOURCE
from .geoboundaries_http import _metadata, _object, _read
from .geoboundaries_resolve import _resolve_inventory
from .io import write_json


def _country_reference(raw: Path) -> dict[str, dict[str, str | int]]:
    record = _metadata(
        "https://download.geonames.org/export/dump/countryInfo.txt",
        raw / "country-reference.json",
    )
    result: dict[str, dict[str, str | int]] = {}
    for line in str(record["body"]).splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        result[fields[1]] = {
            "alpha2": fields[0],
            "population": int(fields[7]),
            "name": fields[4],
        }
    # User-assigned Kosovo code; retain both spellings used in source inventories.
    result["XKX"] = result.get(
        "XKX", {"alpha2": "XK", "population": 0, "name": "Kosovo"}
    )
    return result


def _inventory(workspace: Workspace) -> dict[str, Any]:
    raw = workspace.raw(SOURCE)
    path = raw / "inventory.json"
    if path.exists():
        return _resolve_inventory(workspace, _read(path))
    countries = _country_reference(raw)
    layers: list[dict[str, Any]] = []
    for country, level in [
        ("ALL", "ADM0"),
        ("ALL", "ADM1"),
        *[(c, "ADM2") for c in ADM2_COUNTRIES],
    ]:
        record = _metadata(
            f"{API}/{country}/{level}/", raw / "api" / f"{country}-{level}.json"
        )
        payload = json.loads(record["body"])
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            layer = _object(entry)
            if layer.get("boundaryType") != level or not layer.get("boundaryISO"):
                raise ValueError(f"Invalid API layer: {country}/{level}")
            layers.append(layer)
    layers.sort(
        key=lambda layer: (
            layer["boundaryType"],
            -int(countries.get(layer["boundaryISO"], {}).get("population", 0)),
            layer["boundaryISO"],
        )
    )
    missing = {
        level: sorted(
            set(countries)
            - {
                str(layer["boundaryISO"])
                for layer in layers
                if layer["boundaryType"] == level
            }
        )
        for level in ("ADM0", "ADM1")
    }
    result: dict[str, object] = {
        "source": SOURCE,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_release": "gbOpen-" + fingerprint({"layers": layers})[:20],
        "layers": layers,
        "country_reference": countries,
        "missing_in_api": missing,
        "selection": "All published ADM0/ADM1 and PHL ADM2; no licence filtering",
    }
    write_json(path, result)
    write_json(
        raw / "licenses.json",
        {
            "layers_per_license": dict(
                Counter(str(layer["boundaryLicense"]) for layer in layers)
            ),
            "layers": [
                {
                    key: layer.get(key)
                    for key in (
                        "boundaryID",
                        "boundaryLicense",
                        "licenseDetail",
                        "licenseSource",
                        "boundarySource",
                        "boundaryYearRepresented",
                    )
                }
                for layer in layers
            ],
        },
    )
    return _resolve_inventory(workspace, result)


def _inventory_path(workspace: Workspace) -> Path:
    resolved = workspace.raw(SOURCE) / "inventory-resolved.json"
    return resolved if resolved.exists() else workspace.raw(SOURCE) / "inventory.json"


def _license_path(workspace: Workspace) -> Path:
    resolved = workspace.raw(SOURCE) / "licenses-resolved.json"
    return resolved if resolved.exists() else workspace.raw(SOURCE) / "licenses.json"
