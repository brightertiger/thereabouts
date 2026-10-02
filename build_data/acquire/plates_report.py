"""Regenerate the documentation tables from the published plate artifacts."""

import argparse
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from .artifacts import read_json
from .manifests import load_manifest
from .plates_config import policy
from .workspace import Workspace

MARKER = "<!-- Generated plate coverage below; run plates_report to refresh. -->"
PRIORITY = [
    "IN",
    "CN",
    "DE",
    "ID",
    "TR",
    "RU",
    "IT",
    "PL",
    "GB",
    "JP",
    "VN",
    "MY",
    "IR",
    "TH",
    "PK",
    "UA",
]


def _text(value: Any) -> str:
    return (
        str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")
    )


def _table(headers: list[str], rows: Iterable[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(map(_text, row)) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def report(workspace: Workspace) -> str:
    manifest = load_manifest(workspace, "plates")
    verified = read_json(workspace.normalized("plates") / "verification.json")
    survey: list[dict[str, Any]] = []
    formats: list[dict[str, Any]] = []
    for partition in manifest["partitions"]:
        if partition["kind"] == "plate_survey":
            survey.extend(pq.read_table(partition["path"]).to_pylist())
        elif partition["kind"] == "plate_formats":
            formats.extend(pq.read_table(partition["path"]).to_pylist())
    sources = policy("sources")
    dates = sorted({pin["retrieved_at"][:10] for pin in sources.values()})
    coverage = verified["coverage"]
    lines = [
        MARKER,
        "",
        "## Snapshot and counts",
        "",
        f"Retrieved {dates[0]} through {dates[-1]}; {len(sources):,} pinned files, "
        f"{sum(s['size'] for s in sources.values()):,} bytes. "
        f"Source release: `{manifest['source_release']}`.",
        "",
        f"{verified['output_rows']['plate_codes']:,} code-place evidence rows; "
        f"{verified['distinct_country_codes']:,} distinct (country, code) pairs; "
        f"{verified['distinct_code_strings']:,} distinct code strings. "
        "Different upstream assertions remain separate evidence rows. "
        "Expanded source-written alphabetic ranges account for many Brazilian "
        "and Mexican codes; municipal Wikidata assertions account for many rows.",
        "",
        _table(
            ["Survey class", "Countries/territories"],
            sorted(verified["survey_classes"].items()),
        ),
        f"{len(formats)} format rules in {len({r['country_code'] for r in formats})} "
        f"countries; {sum(bool(r['examples']) for r in formats)} rules have "
        "literal source specimens. A specimen may be illustrative; live issuance "
        "has not been authenticated. Missing examples are empty lists.",
        "",
        f"{verified['identifiers']['wikidata']:,} code rows carry Wikidata IDs; "
        f"{verified['identifiers']['coordinates']:,} have source coordinates. "
        "Identifiers/names from different sources have not been joined.",
        "",
        f"{len(verified['rejected_assertions'])} Wikidata assertions were excluded "
        "as non-codes or unsupported compound expressions. Their original values "
        "and statement IDs are retained in the verification report and raw files.",
        "",
        "## Priority-country coverage",
        "",
        "Counts are distinct original-script code strings, including disagreements. "
        "Current means explicitly classified by that source's parsing policy. "
        "Unknown-period Wikidata statements are included only in the all-period count.",
        "",
    ]
    priority_rows = []
    for country in PRIORITY:
        data = coverage.get(country, {})
        review = verified["reviewed_scopes"].get(country)
        basis = (
            review["basis"]
            if review
            else "Partial: complete current national denominator not established."
        )
        priority_rows.append(
            [
                country,
                data.get("rows", 0),
                data.get("current_codes", 0),
                data.get("distinct_codes", 0),
                basis,
            ]
        )
    lines += [
        _table(
            [
                "Country",
                "Rows",
                "Current codes",
                "All periods",
                "Completeness and basis",
            ],
            priority_rows,
        ),
        "No country is certified complete across every current and historic series. "
        "The following checks cover only the stated published lists:",
        "",
        _table(
            ["Country", "Scope", "Observed / expected", "Check"],
            (
                [
                    cc,
                    r["scope"],
                    f"{r['observed_codes']} / {r['expected_codes']}",
                    r["status"],
                ]
                for cc, r in sorted(verified["reviewed_scopes"].items())
            ),
        ),
        "## Survey of every country and territory",
        "",
        "Universe: the pinned ISO 3166-1 list (249 entries) plus Kosovo (XK). "
        "Disputed/de facto jurisdictions without their own entry are not separately "
        "exhaustive. A class describes the evidenced series, with exceptions in "
        "the last column. `none` is not a claim about every plate ever issued. "
        "A country-universe link on an unverified row provides identity only, "
        "not evidence of plate behavior. Blank levels/positions/dates are unknown.",
        "",
    ]
    survey_rows = []
    for row in sorted(survey, key=lambda r: r["country_code"]):
        data = coverage.get(row["country_code"], {})
        dates_text = f"{row.get('valid_from') or '?'} to {row.get('valid_to') or '?'}"
        survey_rows.append(
            [
                row["country_code"],
                f"[{row['name']}]({row['source_url']})",
                row["classification"],
                row.get("unit_kind"),
                row.get("code_position"),
                f"{row.get('series') or 'unknown'} ({dates_text})",
                f"{data.get('current_codes', 0)} / {data.get('distinct_codes', 0)}",
                data.get("formats", 0),
                row.get("notes"),
            ]
        )
    lines += [
        _table(
            [
                "CC",
                "Country / classification source",
                "Class",
                "Level",
                "Code position",
                "Series (years)",
                "Current / all codes",
                "Formats",
                "Limits / gaps",
            ],
            survey_rows,
        ),
        "## Reproducible cross-checks",
        "",
        "The table compares current code sets when both sources classify current "
        "series. Values unique to a source are retained, not silently resolved. "
        "Different scopes, withdrawn codes, script variants and office/city names "
        "can explain differences. These are not all confirmed factual conflicts. "
        "The [verification report](../data/normalized/plates/verification.json) "
        "contains the complete differing code lists, all-period comparisons "
        "(including Wikidata), per-source counts, and completeness checks. "
        "Place-name equivalence and overlapping geographic claims remain "
        "unadjudicated; consumers must retain the source of each association.",
        "",
        _table(
            [
                "Country",
                "Left source",
                "Right source",
                "Shared",
                "Left only",
                "Right only",
            ],
            (
                [
                    r["country_code"],
                    r["left"],
                    r["right"],
                    r["intersection"],
                    len(r["only_left"]),
                    len(r["only_right"]),
                ]
                for r in verified["current_series_cross_checks"]
            ),
        ),
        "## Format evidence gaps",
        "",
        "Countries with no format rule: "
        + ", ".join(
            r["country_code"]
            for r in sorted(survey, key=lambda r: r["country_code"])
            if not coverage.get(r["country_code"], {}).get("formats")
        )
        + ".",
        "",
        "Rules without literal source specimens: "
        + ", ".join(
            f"{r['country_code']}/{r['series_id']}"
            for r in sorted(formats, key=lambda r: (r["country_code"], r["series_id"]))
            if not r["examples"]
        )
        + ".",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output", type=Path, default=Path("docs/PLATES.md"))
    args = parser.parse_args()
    prefix = args.output.read_text().split(MARKER)[0].rstrip()
    args.output.write_text(prefix + "\n\n" + report(Workspace(args.data_dir)))


if __name__ == "__main__":
    main()
