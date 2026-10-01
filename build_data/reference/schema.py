"""Shared, versioned disk layout; every array excludes Python objects."""

import numpy as np

SCHEMA_VERSION = "1"
POLICY_ID = "ne-geonames-reference-v1"
BOUNDARY_TOLERANCE_DEG = 1e-9
EARTH_RADIUS_KM = 6371.0088
TIE_TOLERANCE_KM = 1e-9

ADMIN_DTYPE = np.dtype(
    [
        ("id", "<u4"),
        ("name", "<u4"),
        ("code", "<u4"),
        ("parent", "<i4"),
        ("subdivisions", "u1"),
    ]
)
PLACE_DTYPE = np.dtype(
    [
        ("id", "<i8"),
        ("name", "<u4"),
        ("feature", "<u4"),
        ("country", "<u4"),
        ("admin1", "<u4"),
    ]
)
LAYERS = ("country", "admin1", "land")
ARRAY_DTYPES = {
    "text": np.dtype("u1"),
    "text_offsets": np.dtype("<u8"),
    "countries": ADMIN_DTYPE,
    "admin1": ADMIN_DTYPE,
    "places": PLACE_DTYPE,
    "coordinates": np.dtype("<f8"),
    "xyz": np.dtype("<f8"),
}
for _layer in LAYERS:
    ARRAY_DTYPES[f"{_layer}_wkb"] = np.dtype("u1")
    ARRAY_DTYPES[f"{_layer}_offsets"] = np.dtype("<u8")
    ARRAY_DTYPES[f"{_layer}_owners"] = np.dtype("<i4")
