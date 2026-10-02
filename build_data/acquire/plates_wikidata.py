"""Preserve P395 statement evidence without inferring present-day eligibility."""

import json
import math
import re
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

Row = dict[str, Any]


def _values(rows: list[Row], key: str) -> list[str]:
    return sorted({row[key]["value"] for row in rows if key in row})


def _one(rows: list[Row], key: str) -> str | None:
    values = _values(rows, key)
    return values[0] if len(values) == 1 else None


def _date(bindings: list[Row], key: str) -> str | None:
    value = _one(bindings, key)
    # Wikidata "some value" qualifiers are blank-node URIs, not timestamps.
    return (
        value if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[0-9:]+Z", value) else None
    )


def rows(path: Path, country_item: str, retrieved_at: str) -> Iterator[Row]:
    data = json.loads(path.read_text(encoding="utf-8"))
    groups: dict[tuple[str, str, str], list[Row]] = defaultdict(list)
    for binding in data["results"]["bindings"]:
        item = binding["item"]["value"].rsplit("/", 1)[-1]
        if item == country_item:
            continue  # International oval country identifiers are not place codes.
        groups[item, binding["statement"]["value"], binding["code"]["value"]].append(
            binding
        )
    for (item, statement, code), bindings in groups.items():
        start, end = _date(bindings, "start"), _date(bindings, "end")
        coordinates = _values(bindings, "coord")
        lat = lon = None
        if len(coordinates) == 1:
            match = re.fullmatch(r"Point\(([-\d.eE+]+) ([-\d.eE+]+)\)", coordinates[0])
            if match:
                x, y = map(float, match.groups())
                if (
                    math.isfinite(x)
                    and math.isfinite(y)
                    and -180 <= x <= 180
                    and -90 <= y <= 90
                ):
                    lon, lat = x, y
        local_names = {
            b["name_local"].get("xml:lang", "und"): b["name_local"]["value"]
            for b in bindings
            if "name_local" in b
        }
        yield dict(
            code=code,
            wikidata_id=item,
            name_en=_one(bindings, "name_en"),
            name_local=_one(bindings, "name_local"),
            local_language=next(iter(local_names)) if len(local_names) == 1 else None,
            unit_kind="wikidata_entity",
            series_id="P395-unspecified",
            series_status="historic"
            if end and end[:10] <= retrieved_at[:10]
            else "unknown",
            valid_from=start,
            valid_to=end,
            latitude=lat,
            longitude=lon,
            geonames_ids=json.dumps(_values(bindings, "geonames")),
            subdivision_codes=json.dumps(_values(bindings, "iso")),
            entity_types=json.dumps(
                [v.rsplit("/", 1)[-1] for v in _values(bindings, "type")]
            ),
            evidence_locator=statement,
            scope="entity_association",
            notes=json.dumps(
                dict(
                    ranks=_values(bindings, "rank"),
                    local_names=local_names,
                    coordinates=coordinates,
                    start_assertions=_values(bindings, "start"),
                    end_assertions=_values(bindings, "end"),
                    warning=(
                        "P395 may repeat a district code on its municipalities; "
                        "no current-series assertion"
                    ),
                ),
                ensure_ascii=False,
            ),
        )
