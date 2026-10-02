"""Read declarative policies; shared, explicitly specified text normalization."""

import json
import re
import unicodedata
from functools import cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).with_name("data")
Row = dict[str, Any]


@cache
def policy(name: str) -> Any:
    return json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))


def normalize(value: str) -> str:
    """NFC; uppercase ASCII only; collapse Unicode whitespace to ASCII space."""
    value = unicodedata.normalize("NFC", value)
    value = value.translate(
        str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    )
    return " ".join(value.split())


def code_key(value: str) -> str:
    """Normalize code separators and decimal glyphs; never transliterate letters."""
    value = normalize(value)
    separators = policy("inference")["code_separators"]
    return "".join(
        str(unicodedata.decimal(c)) if c.isdecimal() else c
        for c in value
        if c not in separators
    )


def scripts(value: str) -> list[str]:
    return [
        name
        for name, pattern in policy("inference")["script_patterns"].items()
        if re.search(pattern, value)
    ]
