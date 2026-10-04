"""Retained source interpretation decisions using the new adapters."""

import json

import pytest

from pipeline.sources.geonames.rows import alias, english_rank, place

PIN: dict[str, object] = {
    "url": "https://example.invalid/geonames.zip",
    "sha256": "0" * 64,
    "retrieved_at": "2026-10-01",
    "last_modified": "2026-10-01",
    "kept_classes": ["A", "P"],
    "license": "CC-BY-4.0",
    "license_url": "https://example.invalid/license",
    "attribution": "GeoNames",
}


def feature(
    identifier: int,
    code: str = "PPL",
    feature_class: str = "P",
    name: str = "Cafe\u0301",
    population: str = "0",
) -> bytes:
    return (
        "\t".join(
            [
                str(identifier),
                name,
                "Cafe",
                "Coffee,Café",
                "1.5",
                "2.5",
                feature_class,
                code,
                "US",
                "CA",
                "01",
                "002",
                "003",
                "004",
                population,
                "42",
                "45",
                "America/New_York",
                "2026-10-01",
            ]
        )
        + "\n"
    ).encode()


def alternate(
    identifier: int,
    entity: int,
    language: str = "en",
    name: str = "Coffee",
    flags: tuple[str, ...] = ("1", "", "", ""),
    start: str = "",
    end: str = "",
) -> bytes:
    return (
        "\t".join([str(identifier), str(entity), language, name, *flags, start, end])
        + "\n"
    ).encode()


def test_broad_rows_and_flags() -> None:
    for code in ("PPL", "PPLX", "PPLH", "PPLQ", "PPLW"):
        row = place(feature(1, code), "test", PIN)
        assert row is not None and row["feature_code"] == code
        assert row["population"] == 0 and row["name"] == "Café"
        assert row["name_en"] is None
        provenance = json.loads(str(row["provenance"]))
        assert provenance["admin3_code"] == "003"
        assert provenance["admin4_code"] == "004"
    for code in ("ADM1", "ADM4", "ADM5", "PCLI", "PCLD", "ADMH"):
        row = place(feature(2, code, "A"), "test", PIN)
        assert row is not None and row["kind"] == "administrative"
    assert place(feature(3, "MT", "T"), "test", PIN) is None
    row = alias(
        alternate(
            2, 1, "link", "https://example.org", ("1", "1", "1", "1"), "1700", "1800"
        ),
        "test",
        PIN,
    )
    assert all(
        row[key] for key in ("is_preferred", "is_short", "is_colloquial", "is_historic")
    )
    assert row["valid_from"] == "1700" and row["valid_to"] == "1800"
    assert english_rank(row) is None


@pytest.mark.parametrize(
    "raw",
    [
        b"bad\n",
        feature(1).replace(b"1.5", b"nan"),
        feature(1, population="-1"),
        feature(0),
    ],
)
def test_invalid_points_are_explicit(raw: bytes) -> None:
    with pytest.raises(ValueError):
        place(raw, "test", PIN)
