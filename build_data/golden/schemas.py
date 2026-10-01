"""Golden Arrow contracts. JSON fields preserve complete source evidence."""

from __future__ import annotations

import pyarrow as pa


def strings(names: str) -> list[pa.Field[pa.DataType]]:
    return [pa.field(name, pa.string()) for name in names.split()]


PLACES = pa.schema(
    [
        *strings(
            "place_id role name name_en local_name country_code code code_status "
            "parent_id parent_method sovereign_id sovereign_code sovereign_name"
        ),
        pa.field("population", pa.int64()),
        *strings(
            "geonames_id geonames_admin1 feature_code "
            "source_subtype settlement_class city_exclusion"
        ),
        pa.field("overture_ids", pa.list_(pa.string())),
        pa.field("wikidata_ids", pa.list_(pa.string())),
        *strings("source_ids provenance name_provenance link"),
    ]
)
CELL_FIELDS: list[pa.Field[pa.DataType]] = [
    pa.field("h3", pa.string(), False),
    pa.field("h3_uint64", pa.uint64(), False),
    pa.field("h3_resolution", pa.uint8(), False),
    *strings(
        "country_id state_id city_id country_method state_method "
        "city_method land_method"
    ),
]
CELLS = pa.schema(CELL_FIELDS)
