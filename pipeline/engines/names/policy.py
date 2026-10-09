"""Validated alternate-name policy and the text folds its rules compare."""

import unicodedata
from dataclasses import dataclass
from typing import Any

from pipeline.config.policies import DIRECTORY, read

PATH = DIRECTORY / "names.yaml"
TREATMENTS = ("keep", "guarded", "drop")


@dataclass(frozen=True)
class Policy:
    linked_methods: tuple[str, ...]
    excluded_languages: frozenset[str]
    colloquial: str
    historic: str
    short: str
    max_folded_length: int


def load() -> dict[str, Any]:
    return read(PATH)


def parse(value: dict[str, Any]) -> Policy:
    for key in ("colloquial", "historic", "short"):
        if value.get(key) not in TREATMENTS:
            raise ValueError(f"Names policy {key} must be one of {TREATMENTS}")
    if int(value["max_folded_length"]) <= 0:
        raise ValueError("Names policy max_folded_length must be positive")
    return Policy(
        tuple(value["linked_methods"]),
        frozenset(value["excluded_languages"]),
        value["colloquial"],
        value["historic"],
        value["short"],
        int(value["max_folded_length"]),
    )


def folded(name: str) -> str:
    """Equal folds always share one index key, whatever the writer's later steps."""
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def guard_key(name: str) -> str:
    """A coarser fold for collision checks; it may merge more than the index does."""
    decomposed = unicodedata.normalize("NFD", folded(name))
    text = "".join(
        c if c.isalnum() else " " for c in decomposed if not unicodedata.combining(c)
    )
    return " ".join(text.split())
