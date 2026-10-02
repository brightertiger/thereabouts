"""File-level retries, shared host throttling, and evidence integrity."""

import io
import time
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from build_data.acquire import plates_http
from build_data.acquire.io import write_json
from build_data.acquire.plates_html import Document
from build_data.acquire.plates_rules import list_rows, regex_rows
from build_data.acquire.plates_wikidata import rows as wikidata_rows


class Response(io.BytesIO):
    def __init__(self, body: bytes, length: int | None = None) -> None:
        super().__init__(body)
        self.headers = {
            "Content-Length": str(length if length is not None else len(body))
        }
        self.url = "https://example.invalid/document"
        self.status = 200


def test_cached_responses_and_shared_per_host_rate_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    delays: list[float] = []

    def respond(request: Any, timeout: int) -> Response:
        assert timeout > 0
        assert "PyOfflineGeocoder" in request.get_header("User-agent")
        calls.append(request.full_url)
        return Response(b"source evidence")

    monkeypatch.setattr(urllib.request, "urlopen", respond)
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    monkeypatch.setattr(time, "sleep", delays.append)
    url = "https://example.invalid/document"
    root = tmp_path / "research"
    first = plates_http.fetch(root, "one", url)
    assert plates_http.fetch(root, "one", url) == first
    plates_http.fetch(tmp_path / "snapshot", "two", url)
    assert calls == [url, url]
    assert delays == pytest.approx([0.0, 1.1])
    with pytest.raises(ValueError, match="Changed URL"):
        plates_http.fetch(root, "one", url + "?changed")
    (root / "one").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="Corrupt"):
        plates_http.fetch(root, "one", url)


def test_truncated_response_is_retained_but_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: Response(b"partial", length=100),
    )
    with pytest.raises(OSError, match="Incomplete HTTP"):
        plates_http.fetch(tmp_path, "body", "https://example.invalid", retries=0)
    assert not (tmp_path / "body").exists()
    assert not (tmp_path / "body.http.json").exists()
    assert [p.read_bytes() for p in tmp_path.glob("*.part")] == [b"partial"]


def test_section_prefixes_and_pdf_prose_keep_source_pairs() -> None:
    doc = Document(
        "<h2>Region (X)</h2><ul><li>A/B North</li><li>C Former South</li></ul>"
    )
    parsed = list(
        list_rows(
            doc,
            dict(
                section_pattern="Region",
                code_prefix_section=r"\((?P<prefix>X)\)",
                item_pattern=r"(?P<codes>[A-Z/]+) (?P<name>.+)",
                code_pattern="[A-Z]",
                unit_kind="district",
                series_status="current",
                historic_pattern="Former",
            ),
        )
    )
    assert [r["code"] for r in parsed] == ["XA", "XB", "XC"]
    assert parsed[-1]["series_status"] == "historic"
    rows = list(
        regex_rows(
            "HEADER North 01 South 402 END",
            dict(
                start="HEADER",
                stop="END",
                item_pattern=r"(?P<name>North|South) (?P<codes>\d{2,3})",
                code_pattern=r"\d+",
                unit_kind="district",
            ),
        )
    )
    assert [(r["code"], r["name_en"]) for r in rows] == [
        ("01", "North"),
        ("402", "South"),
    ]


def test_ordered_list_numbers_are_source_codes_and_nested_lists_do_not_reset() -> None:
    doc = Document(
        '<h2>Districts</h2><ol start="7"><li>North<ul><li>Note</li></ul></li>'
        '<li value="12">South</li><li>East</li></ol>'
    )
    rows = list(
        list_rows(
            doc,
            dict(
                parser="ordered_list",
                section_pattern="Districts",
                item_pattern=r"(?P<codes>\d+) (?P<name>.+)",
                code_pattern=r"\d+",
                unit_kind="district",
            ),
        )
    )
    assert [(r["code"], r["name_en"]) for r in rows] == [
        ("7", "North"),
        ("12", "South"),
        ("13", "East"),
    ]


def test_unknown_and_future_wikidata_dates_do_not_imply_historic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dated.json"
    values = [
        dict(item="http://www.wikidata.org/entity/Q2", statement="Q2-s", code="A"),
        dict(item="http://www.wikidata.org/entity/Q3", statement="Q3-s", code="B"),
    ]
    values[0].update(start="http://www.wikidata.org/.well-known/genid/some-value")
    values[1].update(end="2028-01-01T00:00:00Z")
    write_json(
        path,
        dict(
            results=dict(
                bindings=[{k: {"value": v} for k, v in r.items()} for r in values]
            )
        ),
    )
    parsed = list(wikidata_rows(path, "Q99", "2026-10-02"))
    assert parsed[0]["valid_from"] is None
    assert "genid/some-value" in parsed[0]["notes"]
    assert parsed[1]["valid_to"] == "2028-01-01T00:00:00Z"
    assert {r["series_status"] for r in parsed} == {"unknown"}
