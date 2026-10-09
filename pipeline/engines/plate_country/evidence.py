"""Combine normalized registration codes and pinned official state tables."""

import pyarrow.parquet as pq

from pipeline.sources.plates.html import clean_text
from pipeline.sources.plates.reader import document

from .documents import Pins
from .policy import Row, policy


def code_rows(manifest: Row, sources: Pins) -> list[Row]:
    keep = (
        "source",
        "country_code",
        "code",
        "name_en",
        "name_local",
        "unit_kind",
        "scope",
        "series_status",
        "series_id",
        "subdivision_scope",
        "source_url",
        "license",
        "wikidata_id",
        "subdivision_codes",
        "geonames_ids",
        "latitude",
        "longitude",
    )
    result = []
    for part in manifest["partitions"]:
        if part["kind"] != "plate_codes":
            continue
        for raw in pq.read_table(part["path"]).to_pylist():
            result.append({k: raw[k] for k in keep})
    for rule in policy("state_tables"):
        pin = sources.get(rule["source"])
        if pin is None:
            continue
        for cells in document(pin).tables[rule["table"]].grid()[1:]:
            result.append(
                dict(
                    source=pin["source"],
                    country_code=rule["country_code"],
                    code=clean_text(cells[rule["code_column"]].text),
                    name_en=clean_text(cells[rule["name_column"]].text),
                    name_local=None,
                    unit_kind="state",
                    scope="registration_unit",
                    series_status="current",
                    series_id="state-prefix",
                    subdivision_scope=None,
                    source_url=pin["url"],
                    license=pin["license"],
                )
            )
    return result
