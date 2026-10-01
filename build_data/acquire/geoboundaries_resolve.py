"""Geoboundaries resolve."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from . import Workspace, fingerprint
from .geoboundaries_config import API, SOURCE, _unit
from .geoboundaries_http import _metadata, _object, _read
from .io import write_json


def _resolve_inventory(
    workspace: Workspace, original: dict[str, Any]
) -> dict[str, Any]:
    """Resolve contradictory ALL records through the country's own API response."""
    raw = workspace.raw(SOURCE)
    path = raw / "inventory-resolved.json"
    if path.exists():
        return _read(path)
    layers = list(original["layers"])
    bad: list[dict[str, Any]] = []
    for layer in layers:
        if not str(layer["boundaryID"]).startswith(_unit(layer) + "-"):
            bad.append(layer)
    repaired = [layer for layer in layers if layer not in bad]
    corrections: list[dict[str, object]] = []
    for layer in bad:
        country, level, _ = str(layer["boundaryID"]).split("-", 2)
        record = _metadata(
            f"{API}/{country}/{level}/", raw / "api" / f"{country}-{level}.json"
        )
        replacement = _object(json.loads(record["body"]))
        if (
            replacement["boundaryISO"] != country
            or replacement["boundaryType"] != level
            or not str(replacement["boundaryID"]).startswith(f"{country}-{level}-")
        ):
            raise ValueError("Country API also has inconsistent layer identity")
        corrections.append(
            {
                "original": layer,
                "replacement": replacement,
                "evidence_url": record["url"],
                "reason": "ALL boundaryID contradicts boundaryType and URL",
            }
        )
        if not any(_unit(entry) == _unit(replacement) for entry in repaired):
            repaired.append(replacement)
    if len({_unit(layer) for layer in repaired}) != len(repaired):
        raise ValueError("Duplicate country/level units remain in source inventory")
    countries = _object(original["country_reference"])
    repaired.sort(
        key=lambda layer: (
            layer["boundaryType"],
            -int(countries.get(layer["boundaryISO"], {}).get("population", 0)),
            layer["boundaryISO"],
        )
    )
    result = dict(original)
    result.update(
        layers=repaired,
        source_release="gbOpen-" + fingerprint({"layers": repaired})[:20],
        inventory_corrections=corrections,
    )
    # GeoNames retains two withdrawn ISO entries; report current countries plus XK.
    current = set(countries) - {"ANT", "SCG"}
    result["missing_in_api"] = {
        level: sorted(
            current
            - {
                str(layer["boundaryISO"])
                for layer in repaired
                if layer["boundaryType"] == level
            }
        )
        for level in ("ADM0", "ADM1")
    }
    result["coverage_reference"] = (
        "Frozen GeoNames countryInfo; exclude withdrawn ANT/SCG; "
        "include user-assigned XK"
    )
    write_json(
        raw / "licenses-resolved.json",
        {
            "layers_per_license": dict(
                Counter(str(layer["boundaryLicense"]) for layer in repaired)
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
                for layer in repaired
            ],
        },
    )
    write_json(path, result)
    return result
