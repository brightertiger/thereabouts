"""Evidence field projection; stage inputs supply already verified source bytes."""

from typing import Any

from pipeline.sources.plates.reader import document

from .policy import Row


def source_fields(pin: Row) -> dict[str, Any]:
    return {
        key: pin.get(key)
        for key in (
            "url",
            "license",
            "license_url",
            "attribution",
            "retrieved_at",
            "sha256",
            "revision",
        )
    }


def text_source(pin: Row) -> str:
    return document(pin).text
