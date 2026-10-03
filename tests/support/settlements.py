"""Frozen settlement convention used by committed client test fixtures."""

SETTLEMENT_FEATURE_CODES = (
    "PPL",
    "PPLA",
    "PPLA2",
    "PPLA3",
    "PPLA4",
    "PPLA5",
    "PPLC",
    "PPLF",
    "PPLG",
    "PPLL",
    "PPLR",
    "PPLS",
    "STLMT",
)


def settlement_policy() -> dict[str, object]:
    return {
        "feature_class": "P",
        "feature_codes": list(SETTLEMENT_FEATURE_CODES),
        "rule": (
            "Current populated places; exclude sections and historical, "
            "abandoned or destroyed places"
        ),
        "source": "https://www.geonames.org/export/codes.html",
    }
