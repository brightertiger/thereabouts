"""Narrow geographic prefixes using the pinned territory numbering languages."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import regex

from pipeline.engines.store.codec import Row, rows


class PhoneCountries:
    def __init__(self, paths: list[Path], batch_rows: int) -> None:
        self.patterns: dict[
            str, tuple[str, regex.Pattern[str], regex.Pattern[str] | None]
        ] = {}
        for path in paths:
            for row in rows(path, batch_rows):
                tree = ET.fromstring(row["metadata_xml"])
                # Geographic descriptions describe fixed-line areas, not shared
                # mobile/service allocations in generalDesc.
                pattern = "".join(
                    (tree.findtext("fixedLine/nationalNumberPattern") or "").split()
                )
                if not pattern or row["territory"] == "001":
                    continue
                leading = tree.get("leadingDigits")
                self.patterns[row["territory"]] = (
                    row["calling_code"],
                    regex.compile(pattern),
                    regex.compile(leading) if leading else None,
                )

    def candidates(
        self, prefix: str, original: tuple[str, ...]
    ) -> tuple[tuple[str, ...], str]:
        found = []
        for cc in original:
            entry = self.patterns.get(cc)
            if entry is None:
                # Missing evidence must not manufacture a unique match.
                found.append(cc)
                continue
            calling, pattern, leading = entry
            if not prefix.startswith(calling):
                found.append(cc)
                continue
            national = prefix[len(calling) :]
            if pattern.fullmatch(national, partial=True) is not None and (
                leading is None or leading.match(national, partial=True) is not None
            ):
                found.append(cc)
        return (
            (tuple(found), "territory fixed-line prefix language")
            if found
            else (original, "no numbering-pattern support; retained source candidates")
        )

    def resolve(self, row: Row) -> tuple[list[str], str]:
        candidates, method = self.candidates(row["prefix"], tuple(row["country_codes"]))
        return list(candidates), method
