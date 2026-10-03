"""Read declarative policies; shared, explicitly specified text normalization."""

import re
import unicodedata
from typing import Any

import yaml

from pipeline.config.policies import DIRECTORY, read

DATA = DIRECTORY / "plate_country"
Row = dict[str, Any]


def policy(name: str) -> Any:
    return yaml.load((DATA / f"{name}.yaml").read_bytes(), Loader=yaml.CSafeLoader)


def normalize(value: str) -> str:
    """NFC; uppercase ASCII only; collapse Unicode whitespace to ASCII space."""
    value = unicodedata.normalize("NFC", value)
    value = value.translate(
        str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    )
    return " ".join(value.split())


def code_key(value: str, separators: str | None = None) -> str:
    """Normalize code separators and decimal glyphs; never transliterate letters."""
    value = normalize(value)
    if separators is None:
        separators = policy("inference")["code_separators"]
    return "".join(
        str(unicodedata.decimal(c)) if c.isdecimal() else c
        for c in value
        if c not in separators
    )


def scripts(value: str, patterns: dict[str, str] | None = None) -> list[str]:
    if patterns is None:
        patterns = policy("inference")["script_patterns"]
    if patterns is None:
        raise ValueError("Plate script patterns are missing")
    return [name for name, pattern in patterns.items() if re.search(pattern, value)]


def base_policy(name: str) -> Any:
    return read(DIRECTORY.parent / "sources/plates.yaml")["options"]["policy"][name]
