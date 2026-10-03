"""Country universe/regions and observed vehicle-stock counts from pinned tables."""

import csv
import re
from pathlib import Path

from build_data.acquire.plates_html import clean_text
from build_data.acquire.plates_reader import document

from .policy import Row, policy
from .sources import source_fields


def countries(pin: Row) -> list[Row]:
    with Path(pin["path"]).open(encoding="utf-8") as stream:
        return [
            dict(
                country_code=r["ISO3166-1-Alpha-2"],
                name=r["CLDR display name"],
                region=r["Region Name"] or "Unspecified",
                iso3=r["ISO3166-1-Alpha-3"],
                aliases=sorted(
                    {
                        r[k]
                        for k in (
                            "CLDR display name",
                            "official_name_en",
                            "UNTERM English Short",
                        )
                        if r[k]
                    }
                ),
            )
            for r in csv.DictReader(stream)
        ]


def vehicle_rows(pin: Row, universe: list[Row]) -> tuple[list[Row], list[Row]]:
    names = {
        alias.casefold(): r["country_code"] for r in universe for alias in r["aliases"]
    }
    names.update({k.casefold(): v for k, v in policy("prior_aliases").items()})
    rows, rejected = [], []
    for index, cells in enumerate(document(pin).tables[0].grid()[1:], 1):
        label, _, count, _, year, *_ = (clean_text(c.text) for c in cells)
        name = re.sub(r"\s*\([^)]*\)", "", label).strip()
        country = names.get(name.casefold())
        if (
            country is None
            or not re.fullmatch(r"[0-9, ]+", count)
            or not re.fullmatch(r"[0-9]{4}", year)
        ):
            rejected.append(
                dict(
                    label=label,
                    count=count,
                    year=year,
                    reason="unmapped_country_or_non_numeric_count",
                )
            )
            continue
        rows.append(
            dict(
                country_code=country,
                vehicles=int(re.sub(r"[, ]", "", count)),
                year=int(year),
                source_label=label,
                locator=f"table:0/row:{index}",
                provenance=source_fields(pin),
            )
        )
    return rows, rejected
