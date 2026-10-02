"""Declarative table/list extraction; country choices live in plates/*.json."""

import re
from collections.abc import Iterator
from typing import Any

from .plates_html import Cell, Document, clean_text

Row = dict[str, Any]


def codes(value: str, rule: Row) -> list[str]:
    """Expand only source-written numeric intervals when explicitly enabled."""
    value = value.strip()
    if rule.get("alpha_ranges"):

        def alphabetic(match: re.Match[str]) -> str:
            left, right = match.groups()
            if len(left) != len(right):
                raise ValueError(f"Unequal alphabetic range widths: {match[0]}")

            def number(text: str) -> int:
                result = 0
                for letter in text:
                    result = result * 26 + ord(letter) - ord("A")
                return result

            start, end = number(left), number(right)
            if not start <= end <= start + 20000:
                raise ValueError(f"Excessive alphabetic range: {match[0]}")
            expanded = []
            for n in range(start, end + 1):
                letters = []
                for _ in left:
                    n, remainder = divmod(n, 26)
                    letters.append(chr(ord("A") + remainder))
                code = "".join(reversed(letters))
                if not any(c in code for c in rule.get("excluded_letters", "")):
                    expanded.append(code)
            return ", ".join(expanded)

        value = re.sub(
            r"\b([A-Z]+)\s*(?:[-\u2013\u2014]|to)\s*([A-Z]+)\b", alphabetic, value
        )
    if rule.get("numeric_ranges"):

        def expand(match: re.Match[str]) -> str:
            left, right = match.groups()
            start, end = int(left), int(right)
            if not start <= end <= start + 1000:
                raise ValueError(f"Invalid or excessive code range: {match[0]}")
            return ", ".join(str(n).zfill(len(left)) for n in range(start, end + 1))

        value = re.sub(r"(\d+)\s*(?:[-\u2013\u2014]|to|đến)\s*(\d+)", expand, value)
    return list(
        dict.fromkeys(
            m[0]
            for m in re.finditer(rule["code_pattern"], value)
            if not re.fullmatch(rule.get("code_exclude", r"(?!)"), m[0])
        )
    )


def _row(code: str, name: str, raw: str, rule: Row, locator: str) -> Row:
    name = rule.get("parsed_name") or name
    status = rule.get("series_status", "unknown")
    if rule.get("unknown_pattern") and re.search(rule["unknown_pattern"], raw, re.I):
        status = "unknown"
    if rule.get("historic_pattern") and re.search(rule["historic_pattern"], raw, re.I):
        status = "historic"
    name = re.sub(rule.get("name_remove", r"(?!)"), "", name)
    dates = {}
    for boundary in ("valid_from", "valid_to"):
        found = re.search(rule.get(boundary + "_pattern", r"(?!)"), raw)
        dates[boundary] = found["date"] if found else rule.get(boundary)
    return dict(
        code=clean_text(code),
        name_en=clean_text(name) if rule.get("name_language", "en") == "en" else None,
        name_local=clean_text(name)
        if rule.get("name_language", "en") != "en"
        else None,
        local_language=rule.get("name_language")
        if rule.get("name_language") != "en"
        else None,
        unit_kind=rule["unit_kind"],
        series_status=status,
        **dates,
        series_id=rule.get("series_id", "ordinary"),
        evidence_locator=locator,
        notes=raw,
        scope="registration_unit",
        subdivision_scope=rule.get("subdivision_scope"),
    )


def table_rows(doc: Document, rule: Row) -> Iterator[Row]:
    """Retain all source pairs, including expanded rowspan associations."""
    for index in rule["tables"]:
        table = doc.tables[index]
        grid = table.grid()
        if expected := rule.get("header_contains"):
            header = " ".join(clean_text(c.text) for r in grid[:3] for c in r)
            if expected not in header:
                raise ValueError(f"Table {index}: expected header {expected!r}")
        for number, cells in enumerate(grid):
            if number < rule.get("skip_rows", 1):
                continue
            raw = " | ".join(clean_text(c.text) for c in cells)
            if rule.get("exclude") and re.search(rule["exclude"], raw, re.I):
                continue
            for code_column, name_column in rule["pairs"]:
                code_cell, name_cell = cells[code_column], cells[name_column]
                if not name_cell.text.strip():
                    continue
                if rule.get("name_exclude") and re.search(
                    rule["name_exclude"], name_cell.text, re.I
                ):
                    continue
                selected = codes(code_cell.text, rule)
                if "code_suffix_column" in rule:
                    suffix = codes(
                        cells[rule["code_suffix_column"]].text,
                        {"code_pattern": rule["suffix_pattern"]},
                    )
                    selected = [a + b for a in selected for b in suffix]
                names = re.split(rule.get("name_split", r"(?!)"), name_cell.text)
                for code in selected:
                    for name in names:
                        if not name.strip():
                            continue
                        if rule.get("name_pattern"):
                            match = re.search(rule["name_pattern"], name)
                            if match is None:
                                continue
                            name = match["name"]
                        row = _row(code, name, raw, rule, f"table:{index}/row:{number}")
                        if "local_column" in rule:
                            row["name_local"] = clean_text(
                                cells[rule["local_column"]].text
                            )
                            row["local_language"] = rule.get("local_language")
                        row["place_links"] = name_cell.links
                        yield row


def list_rows(doc: Document, rule: Row) -> Iterator[Row]:
    items = doc.ordered_items if rule.get("parser") == "ordered_list" else doc.items
    if rule.get("parser") == "cell_lines":
        items = [
            (doc.tables[i].section, clean_text(line))
            for i in rule["tables"]
            for row in doc.tables[i].rows
            for cell in row
            for line in cell.text.splitlines()
            if line.strip()
        ]
    for index, (section, text) in enumerate(items):
        if not re.search(rule["section_pattern"], section):
            continue
        if rule.get("exclude") and re.search(rule["exclude"], text, re.I):
            continue
        match = re.match(rule["item_pattern"], text)
        if match is None:
            continue
        prefix = ""
        if rule.get("code_prefix_section"):
            found = re.search(rule["code_prefix_section"], section)
            if found is None:
                raise ValueError(f"Missing section code prefix: {section}")
            prefix = found["prefix"]
        for code in codes(match["codes"], rule):
            for name in re.split(rule.get("name_split", r"(?!)"), match["name"]):
                if name.strip():
                    yield _row(
                        prefix + code, name, text, rule, f"list:{index}/{section}"
                    )


def text_rows(doc: Document, rule: Row) -> Iterator[Row]:
    """Extract explicit prose pairs; policy must capture both code and place."""
    yield from regex_rows(doc.text, rule)


def regex_rows(text: str, rule: Row) -> Iterator[Row]:
    if rule.get("start"):
        text = text[text.index(rule["start"]) :]
    if rule.get("stop"):
        text = text[: text.index(rule["stop"])]
    for substitution in rule.get("text_substitutions", []):
        text = re.sub(substitution["pattern"], substitution["replacement"], text)
    for match in re.finditer(rule["item_pattern"], text):
        prefixes = rule.get("parsed_prefixes", [""])
        if rule.get("code_prefix_group"):
            prefixes = codes(
                match[rule["code_prefix_group"]],
                {"code_pattern": rule["prefix_pattern"]},
            )
        for code in codes(match["codes"], rule):
            for prefix in prefixes:
                for name in re.split(rule.get("name_split", r"(?!)"), match["name"]):
                    if name.strip():
                        row = _row(
                            prefix + code, name, match[0], rule, f"text:{match.start()}"
                        )
                        row["prefix_evidence"] = rule.get("prefix_evidence")
                        yield row


def evidence(doc: Document, pattern: str) -> str:
    """A missing evidence anchor is a hard failure, never a silent default."""
    match = re.search(pattern, doc.text, re.I)
    if match is None:
        raise ValueError(f"Evidence not found: {pattern!r}")
    return match[0]


def cell_text(cells: list[Cell]) -> list[str]:
    return [clean_text(c.text) for c in cells]
