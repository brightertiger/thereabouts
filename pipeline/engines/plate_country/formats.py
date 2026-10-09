"""Normalize accepted and additional format evidence, without country branches."""

import re
from collections.abc import Iterator

from pipeline.sources.plates.html import Document, clean_text
from pipeline.sources.plates.reader import document
from pipeline.sources.plates.rules import evidence

from .documents import Pins
from .policy import Row, base_policy, policy, scripts
from .sources import source_fields
from .syntax import SEPARATORS, TOKEN, relaxed_pattern, specificity, template_pattern


def _decorate(row: Row, source: str, pin: Row) -> Row:
    pattern = row["pattern"]
    re.compile(pattern)
    relaxed = relaxed_pattern(pattern)
    re.compile(relaxed)
    decoded = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), pattern)
    script_text = re.sub(r"\(\?P<[^>]+>|\{[^}]+\}", "", decoded)
    separators: set[str] = set()
    for token in TOKEN.findall(decoded):
        if token in ("|", "."):
            continue
        body = token[1:-1] if token.startswith("[") else token.removeprefix("\\")
        if token.startswith("["):
            body = re.sub(r"[^\\]-[^\\]", "", body)
        separators.update(c for c in body if c in SEPARATORS)
    return dict(
        row,
        source=source,
        provenance=source_fields(pin),
        relaxed_pattern=relaxed,
        scripts=row.get("scripts") or scripts(script_text),
        separators=sorted(separators),
        fixed_national_marks=row.get("fixed_national_marks", []),
        specificity_bits=specificity(pattern),
        coverage="partial_syntax",
    )


def rows(pins: Pins) -> Iterator[Row]:
    """Rules whose source document is not pinned are skipped; the pool counts them."""
    rules = [
        dict(rule, country_code=country)
        for country, items in base_policy("formats").items()
        for rule in items
    ]
    rules.extend(policy("formats"))
    rules.extend(policy("supplemental_formats"))
    documents: dict[str, Document] = {}

    def pinned(source: str) -> tuple[Row, Document] | None:
        pin = pins.get(source)
        if pin is None:
            return None
        if source not in documents:
            documents[source] = document(pin)
        return pin, documents[source]

    for rule in rules:
        source = rule["source"]
        found = pinned(source)
        if found is None:
            continue
        row = {
            k: v
            for k, v in rule.items()
            if k not in ("evidence_pattern", "examples_pattern", "source")
        }
        row["evidence"] = evidence(found[1], rule["evidence_pattern"])
        yield _decorate(row, source, found[0])
    for rule in policy("templates"):
        source = rule["source"]
        found = pinned(source)
        if found is None:
            continue
        cells = found[1].tables[rule["table"]].grid()[rule["row"]]
        cell = clean_text(cells[rule["column"]].text)
        if rule["template"] not in cell:
            raise ValueError(f"Source template changed: {rule}")
        row = dict(
            rule,
            evidence=" | ".join(clean_text(c.text) for c in cells),
            code_group=None,
        )
        row["pattern"] = template_pattern(rule["template"], rule["placeholders"])
        yield _decorate(row, source, found[0])
