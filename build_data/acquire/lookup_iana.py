"""Retain IANA's country associations and representative zone-table points."""

import re
import tarfile
from collections.abc import Iterator
from pathlib import Path

from .lookup_rows import Row, point


def coordinates(value: str) -> Row:
    match = re.fullmatch(r"([+-])(\d{4}|\d{6})([+-])(\d{5}|\d{7})", value)
    if match is None:
        raise ValueError(f"Invalid IANA coordinates: {value}")
    ns, lat, ew, lon = match.groups()

    def angle(text: str, degrees: int) -> float:
        return (
            int(text[:degrees])
            + int(text[degrees : degrees + 2]) / 60
            + (int(text[degrees + 2 :]) / 3600 if len(text) > degrees + 2 else 0)
        )

    return point(
        angle(lat, 2) * (-1 if ns == "-" else 1),
        angle(lon, 3) * (-1 if ew == "-" else 1),
    )


def zone_rows(path: Path) -> Iterator[Row]:
    with tarfile.open(path) as archive:
        for name in ("zone.tab", "zone1970.tab", "zonenow.tab"):
            member = archive.extractfile(name)
            if member is None:
                raise ValueError(f"Missing IANA table {name}")
            for line in member:
                text = line.decode().rstrip("\n")
                if not text or text.startswith("#"):
                    continue
                parts = text.split("\t")
                yield dict(
                    table=name,
                    tzid=parts[2],
                    country_codes=parts[0],
                    comments=parts[3] if len(parts) > 3 else None,
                    coordinates_raw=parts[1],
                    **coordinates(parts[1]),
                )
