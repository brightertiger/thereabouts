"""Fixed-column published lists, including locally extracted PDF evidence."""

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .plates_rules import codes


def pdf_text(path: Path) -> str:
    """Poppler is an explicit build prerequisite for PDF-backed sources."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout


def fixed_rows(text: str, rule: dict[str, Any]) -> Iterator[dict[str, Any]]:
    start = text.index(rule["start"])
    stop = text.index(rule["stop"], start)
    block = text[start:stop]
    exceptions: dict[str, str] = {}
    for pattern in rule.get("exceptions", []):
        match = re.search(pattern, block)
        if match is None:
            raise ValueError(f"Missing fixed-table exception: {pattern}")
        exceptions[match["code"]] = " ".join(match["name"].split())
    name: str | None = None
    for i, line in enumerate(block.splitlines()):
        code_text = line[rule["code_start"] :].strip()
        if not re.fullmatch(rule["code_line_pattern"], code_text):
            continue
        candidate = line[slice(*rule["name_slice"])].strip()
        name = candidate or name
        if name is None:
            raise ValueError("Code continuation has no registration office")
        for code in codes(code_text, rule):
            if code in rule.get("exclude_codes", []):
                continue
            yield dict(
                code=code,
                name_en=exceptions.get(code, name),
                unit_kind=rule["unit_kind"],
                series_status=rule["series_status"],
                series_id=rule["series_id"],
                valid_from=rule.get("valid_from"),
                evidence_locator=f"fixed-table/line:{i}",
                scope="registration_unit",
                notes=line,
            )
