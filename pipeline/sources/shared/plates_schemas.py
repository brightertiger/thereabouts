"""Registration evidence contracts; deliberately no geocoding or H3 assignment."""

from __future__ import annotations

from typing import Literal

import pyarrow as pa

PlateKind = Literal["plate_codes", "plate_survey", "plate_formats"]
PLATE_KINDS: tuple[PlateKind, ...] = ("plate_codes", "plate_survey", "plate_formats")


def _schema(names: str, extra: list[pa.Field[pa.DataType]]) -> pa.Schema:
    return pa.schema(
        [
            pa.field("source", pa.string(), False),
            pa.field("source_id", pa.string(), False),
            *[pa.field(n, pa.string()) for n in names.split()],
            *extra,
            *[
                pa.field(n, pa.string(), False)
                for n in ("source_release", "license", "provenance")
            ],
        ],
        metadata={"acquire_schema_version": "1", "plates_schema_version": "1"},
    )


PLATE_SCHEMAS: dict[PlateKind, pa.Schema] = {
    "plate_codes": _schema(
        "country_code code name_en name_local local_language unit_kind "
        "series_status valid_from valid_to wikidata_id geonames_ids "
        "subdivision_codes entity_types source_url retrieved_at evidence_locator "
        "notes scope series_id subdivision_scope",
        [pa.field("latitude", pa.float64()), pa.field("longitude", pa.float64())],
    ),
    "plate_survey": _schema(
        "country_code name classification unit_kind code_position series "
        "valid_from valid_to evidence source_url retrieved_at notes coverage_status",
        [],
    ),
    "plate_formats": _schema(
        "country_code series_id series_status pattern code_group code_position "
        "normalization valid_from valid_to evidence source_url retrieved_at notes "
        "subdivision_scope",
        [pa.field("examples", pa.list_(pa.string()), False)],
    ),
}
