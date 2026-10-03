"""Fixed place records with nullable, lazily decoded UTF-8 fields."""

from pathlib import Path
from typing import Any

from .container import Container
from .errors import CorruptPackError
from .jsonio import parse, relative_name, string
from .layout import (
    CATALOGUE,
    OFFSETS,
    PLACE,
    PLACES,
    REFERENCE_FIELDS,
    REQUIRED_TEXT,
    ROLES,
    TEXT,
    TEXT_FIELDS,
    U64,
)


class Catalogue(Container):
    def __init__(self, path: Path, total: int) -> None:
        super().__init__(path, CATALOGUE)
        self.total = total
        if self.sections[OFFSETS].count < 2:
            self.close()
            raise CorruptPackError("Missing null string and terminal offset")

    def text(self, index: int) -> str | None:
        offsets, text = self.sections[OFFSETS], self.sections[TEXT]
        if not 0 <= index < offsets.count - 1:
            raise CorruptPackError("Invalid string reference")
        start = U64.unpack_from(self.data, offsets.offset + index * 8)[0]
        stop = U64.unpack_from(self.data, offsets.offset + (index + 1) * 8)[0]
        if not 0 <= start <= stop <= text.size:
            raise CorruptPackError("Invalid UTF-8 span")
        if index == 0:
            if start or stop:
                raise CorruptPackError("Null string must have an empty span at zero")
            return None
        try:
            return self.data[text.offset + start : text.offset + stop].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CorruptPackError("Invalid UTF-8") from exc

    def record(self, index: int) -> dict[str, Any]:
        span = self.sections[PLACES]
        if not 0 <= index < span.count:
            raise CorruptPackError("Invalid place reference")
        fields = PLACE.unpack_from(self.data, span.offset + index * PLACE.size)
        value: dict[str, Any] = {
            name: self.text(fields[i]) for i, name in enumerate(TEXT_FIELDS)
        }
        if any(not value[name] for name in REQUIRED_TEXT) or value["role"] not in ROLES:
            raise CorruptPackError("Missing required place field or invalid role")
        for name, ref in zip(REFERENCE_FIELDS, fields[len(TEXT_FIELDS) :], strict=True):
            if ref > self.total:
                raise CorruptPackError("Dangling place reference")
            value[name] = ref
        try:
            evidence = parse(value["evidence"])
            if set(evidence) != {"golden_table", "source_ids", "name_provenance"}:
                raise ValueError("Invalid place evidence fields")
            relative_name(string(evidence["golden_table"]))
            value["evidence"] = evidence
        except (ValueError, TypeError) as exc:
            raise CorruptPackError("Invalid place evidence") from exc
        return value

    def verify(self) -> None:
        offsets = self.sections[OFFSETS]
        for index in range(offsets.count - 1):
            self.text(index)
        end = U64.unpack_from(self.data, offsets.offset + offsets.size - 8)[0]
        if end != self.sections[TEXT].size:
            raise CorruptPackError("Unreferenced text bytes")
        for index in range(self.sections[PLACES].count):
            self.record(index)
