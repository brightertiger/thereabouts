"""Little-endian serving records, independent of the original H3 runtime."""

from struct import Struct

MAGIC = b"THEREPK\0"
MAJOR, MINOR = 1, 0
HEADER = Struct("<8sHHIIIQ")
SECTION = Struct("<IIQQQ")
DIRECTORY = Struct("<IIQIIQQ")
LABEL = Struct("<IIII")
PLACE = Struct("<16I")
U16, U64 = Struct("<H"), Struct("<Q")
ALIGNMENT = 8
SPATIAL, CATALOGUE, EXACT = 1, 2, 3
CODE_INDEX, CODE_KEYS, CODE_PAYLOADS = 8, 9, 10
KEY_RECORD = Struct("<QIIQQQ")
BLOCKS, KEYS, VALUES, LABELS = 1, 2, 3, 4
PLACES, OFFSETS, TEXT = 5, 6, 7
SECTIONS = {
    SPATIAL: (BLOCKS, KEYS, VALUES, LABELS),
    CATALOGUE: (PLACES, OFFSETS, TEXT),
    EXACT: (CODE_INDEX, CODE_KEYS, CODE_PAYLOADS),
}
WIDTHS = {
    BLOCKS: DIRECTORY.size,
    KEYS: 2,
    VALUES: 1,
    LABELS: 16,
    PLACES: PLACE.size,
    OFFSETS: 8,
    TEXT: 1,
    CODE_INDEX: KEY_RECORD.size,
    CODE_KEYS: 1,
    CODE_PAYLOADS: 1,
}
REFERENCE_RESOLUTION, BLOCK_RESOLUTION = 8, 3
CHILD_RADIX = 7
H3_MAX_RESOLUTION = 15
H3_BASE_SHIFT, H3_BASE_MASK = 45, 127
H3_RESOLUTION_SHIFT, H3_CELL_MODE = 52, 1 << 59
H3_DIGIT_BITS, H3_DIGIT_MASK = 3, 7
MAX_BLOCK_ROWS = CHILD_RADIX ** (REFERENCE_RESOLUTION - BLOCK_RESOLUTION)
MAX_KEY = (CHILD_RADIX**6 - 1) // (CHILD_RADIX - 1) - 1
BLOCK_COUNT = 122 * CHILD_RADIX**BLOCK_RESOLUTION
REAL_BLOCK_COUNT = 41162
UINT32_MAX = 2**32 - 1
DEFAULT_SHARD_BYTES = 64 * 1024 * 1024
CITY_METHOD_MASK, COUNTRY_AREA, STATE_AREA, OFFSHORE = 7, 8, 16, 32
LABEL_FLAGS_MASK = 63

CITY_METHODS = (
    None,
    "city_polygon",
    "policy_polygon",
    "urban_allocation",
    "town_radius",
    "rural_polygon",
    "rural_nearest",
    "rural_nearest_distant",
)
TEXT_FIELDS = (
    "place_id",
    "name",
    "name_en",
    "local_name",
    "role",
    "settlement_kind",
    "country_code",
    "code",
    "code_status",
    "parent_method",
    "normalization_method",
    "evidence",
)
REFERENCE_FIELDS = ("country_id", "parent_id", "sovereign_id", "normalized_city_id")
REQUIRED_TEXT = {
    "place_id",
    "name",
    "role",
    "settlement_kind",
    "country_code",
    "evidence",
}
ROLES = {"country", "state", "district", "city", "town", "settlement"}


def aligned(size: int) -> int:
    return (size + ALIGNMENT - 1) // ALIGNMENT * ALIGNMENT


def encode_flags(
    city: str | None, country: str | None, state: str | None, land: str
) -> int:
    if city not in CITY_METHODS or country not in (None, "area"):
        raise ValueError("Unsupported golden assignment method")
    if state not in (None, "area") or land not in ("land", "offshore"):
        raise ValueError("Unsupported golden assignment method")
    return (
        CITY_METHODS.index(city)
        | (COUNTRY_AREA if country is not None else 0)
        | (STATE_AREA if state is not None else 0)
        | (OFFSHORE if land == "offshore" else 0)
    )


def check_label(label: tuple[int, int, int, int], places: int) -> None:
    country, state, city, flags = label
    if max(country, state, city) > places or flags & ~LABEL_FLAGS_MASK:
        raise ValueError("Invalid label reference or reserved flags")
    if (
        bool(city) != bool(flags & CITY_METHOD_MASK)
        or bool(country) != bool(flags & COUNTRY_AREA)
        or bool(state) != bool(flags & STATE_AREA)
    ):
        raise ValueError("Place and method nulls disagree")
