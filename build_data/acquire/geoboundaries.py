"""Acquire every gbOpen ADM0/ADM1 and PHL ADM2, retaining source semantics."""

from __future__ import annotations

import fcntl
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.client import HTTPException, HTTPResponse
from pathlib import Path
from typing import Any, cast

from . import Ledger, Workspace, download_file, fingerprint
from .io import write_json

SOURCE = "geoboundaries"
API = "https://www.geoboundaries.org/api/current/gbOpen"
REPO_API = "https://api.github.com/repos/wmgeolab/geoBoundaries"
MEDIA = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries"
SOURCE_BUDGET = 12_000_000_000
DOWNLOAD_VERSION = "1"
ADM2_COUNTRIES = ("PHL",)
HEADERS = {"Accept-Encoding": "identity", "User-Agent": "PyOfflineGeocoder/acquire"}
RETRY_ERRORS = (OSError, HTTPException)


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return cast(dict[str, Any], value)


def _read(path: Path) -> dict[str, Any]:
    return _object(json.loads(path.read_text(encoding="utf-8")))


def _request(
    url: str, *, method: str = "GET", headers: dict[str, str] | None = None
) -> HTTPResponse:
    request = urllib.request.Request(
        url, method=method, headers=HEADERS | (headers or {})
    )
    for attempt in range(6):
        try:
            return cast(HTTPResponse, urllib.request.urlopen(request, timeout=60))
        except RETRY_ERRORS:
            if attempt == 5:
                raise
            time.sleep(min(2**attempt, 30))
    raise AssertionError("Unreachable retry loop")


def _metadata(url: str, path: Path) -> dict[str, Any]:
    if path.exists():
        return _read(path)
    with _request(url) as response:
        data = response.read(8_000_001)
        if len(data) > 8_000_000:
            raise ValueError("Metadata response exceeds 8 MB")
        record: dict[str, object] = {
            "url": url,
            "resolved_url": response.url,
            "retrieved_at": datetime.now(UTC).isoformat(),
            "etag": response.getheader("ETag"),
            "last_modified": response.getheader("Last-Modified"),
            "body": data.decode("utf-8"),
        }
    write_json(path, record)
    return record


@contextmanager
def _lock(workspace: Workspace, stage: str) -> Iterator[None]:
    path = workspace.work / f"{SOURCE}-{stage}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                f"Another {SOURCE} {stage} process owns {path}"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


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


def _unit(layer: dict[str, Any]) -> str:
    return f"{layer['boundaryISO']}-{layer['boundaryType']}"


def _inventory_path(workspace: Workspace) -> Path:
    resolved = workspace.raw(SOURCE) / "inventory-resolved.json"
    return resolved if resolved.exists() else workspace.raw(SOURCE) / "inventory.json"


def _license_path(workspace: Workspace) -> Path:
    resolved = workspace.raw(SOURCE) / "licenses-resolved.json"
    return resolved if resolved.exists() else workspace.raw(SOURCE) / "licenses.json"


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


def _pin_path(workspace: Workspace, layer: dict[str, Any]) -> Path:
    path = workspace.raw(SOURCE) / "pins" / f"{_unit(layer)}.json"
    if path.exists() and _read(path)["metadata"] != layer:
        return path.with_name(f"{_unit(layer)}-{fingerprint(layer)[:16]}.json")
    return path


def _pin(workspace: Workspace, layer: dict[str, Any]) -> dict[str, Any]:
    raw = workspace.raw(SOURCE)
    path = _pin_path(workspace, layer)
    if path.exists():
        return _read(path)
    url = str(layer["staticDownloadLink"])
    match = re.fullmatch(
        r"https://github.com/wmgeolab/geoBoundaries/raw/([0-9a-f]{7,40})/(.+)", url
    )
    if match is None:
        raise ValueError(f"Unexpected non-pinned layer URL: {url}")
    short, suffix = match.groups()
    record = _metadata(f"{REPO_API}/commits/{short}", raw / "commits" / f"{short}.json")
    commit = str(_object(json.loads(record["body"]))["sha"])
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None or not commit.startswith(short):
        raise ValueError("Commit did not resolve to a matching full SHA")
    resolved = f"{MEDIA}/{commit}/{suffix}"
    with _request(resolved, method="HEAD") as response:
        size = int(response.getheader("Content-Length", "0"))
        etag = response.getheader("ETag")
        modified = response.getheader("Last-Modified")
    if size <= 0 or not etag or etag.startswith("W/"):
        raise ValueError("Layer needs a known size and a strong immutable ETag")
    end = min(31, size - 1)
    with _request(
        resolved, headers={"Range": f"bytes=0-{end}", "If-Range": etag}
    ) as response:
        if (
            response.status != 206
            or response.getheader("Content-Range") != f"bytes 0-{end}/{size}"
            or response.getheader("ETag") != etag
            or len(response.read(end + 2)) != end + 1
        ):
            raise ValueError("Layer route failed the pinned byte-range probe")
    result: dict[str, object] = {
        "url": resolved,
        "original_url": url,
        "commit": commit,
        "size": size,
        "etag": etag,
        "last_modified": modified,
        "range_verified": True,
        "retrieved_at": datetime.now(UTC).isoformat(),
        "metadata": layer,
    }
    write_json(path, result)
    return result


def _source_size(workspace: Workspace) -> int:
    roots = (
        workspace.raw(SOURCE),
        workspace.normalized(SOURCE),
        *workspace.work.glob(f"{SOURCE}*"),
    )
    total = 0
    for root in roots:
        entries = (root,) if root.is_file() else root.rglob("*")
        for path in entries:
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                # Our downloader and normalizer can publish different units.
                continue
    return total


def _budget(workspace: Workspace, required: int) -> None:
    workspace.check_budget(required)
    if _source_size(workspace) + required > SOURCE_BUDGET:
        raise OSError(
            "geoBoundaries 12 GB budget reached; remaining layers are not empty"
        )


def _archive_path(workspace: Workspace, pin: dict[str, Any]) -> Path:
    return (
        workspace.raw(SOURCE)
        / str(pin["commit"])
        / f"{_unit(_object(pin['metadata']))}.zip"
    )


def _archive_check(path: Path) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"ZIP CRC failure: {bad}")
        names = archive.namelist()
        if not any(name.endswith(".shp") for name in names):
            raise ValueError("Layer ZIP contains no shapefile")
        return {
            "zip_crc": "passed",
            "members": names,
            "expanded_bytes": sum(info.file_size for info in archive.infolist()),
        }


def _download(workspace: Workspace) -> None:
    started = time.monotonic()
    inventory = _inventory(workspace)
    ledger = Ledger(workspace.ledger_path)
    report_path = workspace.work / f"{SOURCE}-download-report.json"
    report: dict[str, Any] = {
        "source_release": inventory["source_release"],
        "started_at": datetime.now(UTC).isoformat(),
        "completed": {},
        "failed": {},
        "finished": False,
    }
    for layer in inventory["layers"]:
        unit = _unit(layer)
        try:
            pin = _pin(workspace, layer)
            inputs_hash = fingerprint({"pin": pin, "builder": DOWNLOAD_VERSION})
            path = _archive_path(workspace, pin)
            if not ledger.is_complete(f"{SOURCE}.download", unit, inputs_hash):
                _budget(workspace, int(pin["size"]) * 2)
                print(f"DOWNLOAD {unit} {pin['size']} bytes", flush=True)
                download_file(
                    str(pin["url"]),
                    path,
                    expected_size=int(pin["size"]),
                    etag=str(pin["etag"]),
                )
                checked = _archive_check(path)
                ledger.complete(
                    f"{SOURCE}.download", unit, inputs_hash, [path], metadata=checked
                )
            report["completed"][unit] = {"path": str(path), "size": path.stat().st_size}
            print(
                f"VERIFIED {unit} ({len(report['completed'])}/"
                f"{len(inventory['layers'])})",
                flush=True,
            )
        except (OSError, ValueError, HTTPException, zipfile.BadZipFile) as error:
            report["failed"][unit] = f"{type(error).__name__}: {error}"
            print(f"FAILED {unit}: {error}", flush=True)
        report["elapsed_seconds"] = time.monotonic() - started
        write_json(report_path, report)
    report["finished"] = True
    write_json(report_path, report)
    if report["failed"]:
        raise RuntimeError(
            f"{len(report['failed'])} geoBoundaries layers failed; see {report_path}"
        )


def download(workspace: Workspace) -> None:
    """Download immutable, CRC-verified layer ZIPs; retry failed units on rerun."""
    with _lock(workspace, "download"):
        _download(workspace)


def normalize(workspace: Workspace) -> None:
    """Publish bounded areas; implemented in the source-owned normalization helper."""
    from .geoboundaries_normalize import normalize_layers

    with _lock(workspace, "normalize"):
        normalize_layers(workspace)
