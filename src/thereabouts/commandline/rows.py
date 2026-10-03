"""Stream tabular input without logging raw query values."""

import csv
from collections.abc import Iterator
from typing import Literal, TextIO

from ..packs.jsonio import parse


def rows(
    stream: TextIO,
    *,
    format: str,
    kind: Literal["coordinates", "h3"],
    latitude: str,
    longitude: str,
    cell: str,
) -> Iterator[object]:
    if format == "jsonl":
        for line in stream:
            try:
                value = parse(line)
                yield (
                    value[cell] if kind == "h3" else (value[latitude], value[longitude])
                )
            except (ValueError, KeyError, TypeError):
                yield None
        return
    try:
        reader = csv.DictReader(stream, strict=True)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            yield None
            return
        for value in reader:
            try:
                yield (
                    value[cell]
                    if kind == "h3"
                    else (float(value[latitude]), float(value[longitude]))
                )
            except (ValueError, KeyError, TypeError):
                yield None
    except csv.Error:
        yield None
