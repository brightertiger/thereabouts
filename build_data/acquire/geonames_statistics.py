"""Pinned publisher statistics, independent from daily dump checkpoint identity."""

from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from http.client import HTTPResponse
from pathlib import Path
from typing import cast

from . import Workspace, atomic_output, sha256_file
from .geonames_download import budget, now, read_json
from .io import write_json

URL = "https://www.geonames.org/statistics/total.html"
MAX_BYTES = 2_000_000


class _Cells(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.row: list[str] = []
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif tag == "td":
            self.cell = []

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)


def parse_counts(html: str) -> dict[str, int]:
    parser = _Cells()
    parser.feed(html)
    counts: dict[str, int] = {}
    for row in parser.rows:
        if len(row) < 2:
            continue
        number, label = row[:2]
        if re.fullmatch(r"[\d,]+", number) is None:
            continue
        if re.fullmatch(r"[A-Z]\.[A-Z0-9]+", label):
            counts[label] = int(number.replace(",", ""))
        elif re.fullmatch(r"Total for [A-Z]", label):
            counts[label[-1]] = int(number.replace(",", ""))
    if not {"P", "A"} <= counts.keys():
        raise ValueError("Publisher statistics page has no P/A totals")
    return counts


def _validate_counts(path: Path) -> None:
    parse_counts(path.read_text(encoding="utf-8"))


def download_statistics(workspace: Workspace) -> None:
    """Capture a small metadata page once, preserving retrieval time and validators."""
    root = workspace.raw("geonames") / "statistics"
    path, receipt = root / "total.html", root / "receipt.json"
    if receipt.exists():
        saved = read_json(receipt)
        if path.exists() and sha256_file(path) == saved["sha256"]:
            return
        raise ValueError("Pinned GeoNames statistics snapshot is corrupt")
    budget(workspace, MAX_BYTES)
    with cast(HTTPResponse, urllib.request.urlopen(URL, timeout=60)) as response:
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("GeoNames statistics metadata exceeds 2 MB")
        metadata: dict[str, object] = {
            "url": URL,
            "resolved_url": response.geturl(),
            "retrieved_at": now(),
            "etag": response.getheader("ETag"),
            "last_modified": response.getheader("Last-Modified"),
            "size": len(content),
            "counts": parse_counts(content.decode("utf-8")),
        }
    with atomic_output(path, _validate_counts) as temp:
        temp.write_bytes(content)
    metadata["sha256"] = sha256_file(path)
    write_json(receipt, metadata)


def comparison(
    workspace: Workspace, classes: dict[str, int], codes: dict[str, int]
) -> dict[str, object]:
    receipt = workspace.raw("geonames") / "statistics" / "receipt.json"
    if not receipt.exists():
        return {"verified": False, "reason": "No pinned publisher statistics snapshot"}
    saved = read_json(receipt)
    if sha256_file(receipt.with_name("total.html")) != saved["sha256"]:
        raise ValueError("Publisher statistics checksum mismatch")
    published = cast(dict[str, int], saved["counts"])
    observed = {**codes, **classes}
    differences = {
        code: {
            "observed": observed.get(code, 0),
            "published": count,
            "difference": observed.get(code, 0) - count,
        }
        for code, count in published.items()
        if (len(code) == 1 or code.startswith(("P.", "A.")))
        and observed.get(code, 0) != count
    }
    return {
        "url": saved["url"],
        "retrieved_at": saved["retrieved_at"],
        "sha256": saved["sha256"],
        "published": published,
        "compared": True,
        "exact_match": not differences,
        "differences": differences,
        "qualification": "Live site statistics and daily dump are not a shared "
        "snapshot. Exact extracted dump line accounting is verified independently.",
    }


def artifacts(workspace: Workspace) -> list[Path]:
    root = workspace.raw("geonames") / "statistics"
    return [
        path for path in (root / "total.html", root / "receipt.json") if path.exists()
    ]
