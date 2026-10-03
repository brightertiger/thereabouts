"""Read fetched plate evidence and apply auditable declarative policies."""

import csv
import json
import re
from collections.abc import Iterator
from html import escape
from pathlib import Path
from typing import Any

from pipeline.sources.shared.plates_schemas import PlateKind

from .html import Document
from .rules import codes, evidence, list_rows, regex_rows, table_rows, text_rows
from .text import fixed_rows, pdf_text
from .wikidata import rows as wikidata_rows
from .wikipedia import wiki_document

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


def survey(inventory: Row, policies: Row) -> Iterator[tuple[PlateKind, Row, str]]:
    rules = policies["survey"]
    universe = {raw["ISO3166-1-Alpha-2"]: raw for raw in country_rows(inventory)}
    for country, rule in rules.items():
        if country not in universe:
            universe[country] = {"CLDR display name": rule["name"]}
    for country, raw in universe.items():
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


def formats(
    inventory: Row, policies: Row, example_limit: int
) -> Iterator[tuple[PlateKind, Row, str]]:
    for country, rules in policies["formats"].items():
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
            )[:example_limit]
            for example in row["examples"]:
                if re.fullmatch(rule["pattern"], example) is None:
                    raise ValueError(
                        f"Example mismatch {country}/{rule['series_id']}: {example}"
                    )
            yield "plate_formats", row, source


def records(
    inventory: Row,
    policies: Row,
    example_limit: int,
    rejections: list[Row] | None = None,
) -> Iterator[tuple[PlateKind, Row, str]]:
    rules = policies["rules"]
    countries = {
        r["ISO3166-1-Alpha-2"]: r["wikidata_id"].rsplit("/", 1)[-1]
        for r in country_rows(inventory)
    }
    yield from survey(inventory, policies)
    yield from formats(inventory, policies, example_limit)
    for source, pin in inventory["files"].items():
        country = pin.get("country_code")
        if pin["kind"] == "wikidata":
            rejected: list[Row] = []
            for row in wikidata_rows(
                Path(pin["path"]),
                countries[country],
                pin["retrieved_at"],
                policies["wikidata"].get(country, {}),
                rejected,
            ):
                row["country_code"] = country
                yield "plate_codes", row, source
            if rejections is not None:
                rejections.extend(
                    dict(**r, source=source, country_code=country) for r in rejected
                )
        if source not in rules:
            continue
        if pin["kind"] == "pdf":
            text = pdf_text(Path(pin["path"]))
            for rule in rules[source]:
                if context := rule.get("prefix_source"):
                    other = inventory["files"][context["source"]]
                    other_text = pdf_text(Path(other["path"]))
                    match = re.search(context["pattern"], other_text)
                    if match is None:
                        raise ValueError(f"Missing prefix evidence: {context}")
                    rule = dict(
                        **rule,
                        parsed_prefixes=codes(match["prefixes"], context),
                        parsed_name=match.groupdict().get("name"),
                        prefix_evidence=dict(
                            source=context["source"],
                            url=other["url"],
                            sha256=other["sha256"],
                            text=match[0],
                        ),
                    )
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
