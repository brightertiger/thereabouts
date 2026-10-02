"""Public normalization tables; source identities remain the join keys."""

import pyarrow as pa

CITIES = pa.schema(
    [
        pa.field(n, pa.string(), False)
        for n in ("city_id", "place_id", "country_code", "kind", "name", "eligibility")
    ]
    + [
        pa.field("name_en", pa.string()),
        pa.field("latitude", pa.float64(), False),
        pa.field("longitude", pa.float64(), False),
        pa.field("population", pa.int64()),
        pa.field("source_ids", pa.string(), False),
        pa.field("footprint_references", pa.string(), False),
        pa.field("allocation_rule", pa.string(), False),
    ]
)
MAPPING = pa.schema(
    [
        pa.field("place_id", pa.string(), False),
        pa.field("city_id", pa.string()),
        pa.field("method", pa.string(), False),
        pa.field("evidence", pa.string()),
    ]
)
