"""Read fetched plate evidence and apply auditable declarative policies."""

import csv
import json
import re
from collections.abc import Iterator
from html import escape
from pathlib import Path
from typing import Any

from .plates_config import policy
from .plates_html import Document
from .plates_http import wiki_document
from .plates_rules import evidence, list_rows, regex_rows, table_rows, text_rows
from .plates_schemas import PlateKind
from .plates_text import fixed_rows, pdf_text
from .plates_wikidata import rows as wikidata_rows

Row = dict[str, Any]


def document(pin: Row) -> Document:
    path = Path(pin["path"])
    if pin["kind"] == "pdf":
        return Document(escape(pdf_text(path)))
    if pin["kind"] != "wikipedia":
        return Document(path.read_text(encoding=pin.get("encoding", "utf-8")))
    html, revision = wiki_document(path)
    if revision != pin["revision"]:
        raise ValueError("Wrong Wikipedia revision")
    return Document(html)


def country_rows(inventory: Row) -> list[Row]:
    with Path(inventory["files"]["countries.csv"]["path"]).open(
        encoding="utf-8"
    ) as stream:
        return list(csv.DictReader(stream))


def survey(inventory: Row) -> Iterator[tuple[PlateKind, Row, str]]:
    rules = policy("survey")
    for raw in country_rows(inventory):
        country = raw["ISO3166-1-Alpha-2"]
        rule = rules.get(country)
        source = rule["source"] if rule else "countries.csv"
        if rule:
            doc = document(inventory["files"][source])
            row = {
                k: v for k, v in rule.items() if k not in ("source", "evidence_pattern")
            }
            row["evidence"] = evidence(doc, rule["evidence_pattern"])
        else:
            row = dict(
                classification="unverified",
                coverage_status="gap",
                notes=(
                    "No reviewed classification evidence; "
                    "do not infer absence of geographic coding."
                ),
                evidence=json.dumps(raw, ensure_ascii=False),
            )
        row.update(country_code=country, name=raw["CLDR display name"])
        yield "plate_survey", row, source
    if "XK" in rules:
        rule = rules["XK"]
        doc = document(inventory["files"][rule["source"]])
        row = {k: v for k, v in rule.items() if k not in ("source", "evidence_pattern")}
        row.update(
            country_code="XK",
            name="Kosovo",
            evidence=evidence(doc, rule["evidence_pattern"]),
        )
        yield "plate_survey", row, rule["source"]


def formats(inventory: Row) -> Iterator[tuple[PlateKind, Row, str]]:
    for country, rules in policy("formats").items():
        for rule in rules:
            source = rule["source"]
            doc = document(inventory["files"][source])
            row = {
                k: v
                for k, v in rule.items()
                if k not in ("source", "evidence_pattern", "examples_pattern")
            }
            row.update(
                country_code=country, evidence=evidence(doc, rule["evidence_pattern"])
            )
            row["examples"] = list(
                dict.fromkeys(
                    m[0]
                    for m in re.finditer(
                        rule.get("examples_pattern", r"(?!)"), doc.text
                    )
                )
            )[:5]
            for example in row["examples"]:
                if re.fullmatch(rule["pattern"], example) is None:
                    raise ValueError(
                        f"Example mismatch {country}/{rule['series_id']}: {example}"
                    )
            yield "plate_formats", row, source


def records(inventory: Row) -> Iterator[tuple[PlateKind, Row, str]]:
    rules = policy("rules")
    countries = {
        r["ISO3166-1-Alpha-2"]: r["wikidata_id"].rsplit("/", 1)[-1]
        for r in country_rows(inventory)
    }
    yield from survey(inventory)
    yield from formats(inventory)
    for source, pin in inventory["files"].items():
        country = pin.get("country_code")
        if pin["kind"] == "wikidata":
            for row in wikidata_rows(
                Path(pin["path"]), countries[country], pin["retrieved_at"]
            ):
                row["country_code"] = country
                yield "plate_codes", row, source
        if source not in rules:
            continue
        if pin["kind"] == "pdf":
            text = pdf_text(Path(pin["path"]))
            for rule in rules[source]:
                pdf_parser = regex_rows if rule["parser"] == "text" else fixed_rows
                count = 0
                for row in pdf_parser(text, rule):
                    count += 1
                    row["country_code"] = rule.get("country_code", country)
                    yield "plate_codes", row, source
                if not count:
                    raise ValueError(f"PDF rule extracted no records: {source}")
            continue
        doc = document(pin)
        seen: set[str] = set()
        for rule in rules[source]:
            parser = {
                "table": table_rows,
                "text": text_rows,
                "list": list_rows,
                "cell_lines": list_rows,
                "ordered_list": list_rows,
            }[rule["parser"]]
            count = 0
            for row in parser(doc, rule):
                row["country_code"] = rule.get("country_code", country)
                key = json.dumps(
                    {
                        k: row.get(k)
                        for k in (
                            "code",
                            "name_en",
                            "name_local",
                            "series_id",
                            "series_status",
                            "valid_from",
                            "valid_to",
                        )
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                )
                count += 1
                if key not in seen:
                    seen.add(key)
                    yield "plate_codes", row, source
            if not count:
                raise ValueError(f"Rule extracted no records: {source}: {rule}")
