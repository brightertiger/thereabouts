"""Pinned source snapshots; network access exists only in explicit builds."""

import hashlib
import shutil
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    sha256: str
    date: str
    version: str
    license: str
    license_url: str
    attribution: str
    retrieved_date: str = "2026-10-01"


_NE = "https://naturalearth.s3.amazonaws.com/"
SOURCES = (
    Source(
        "countries",
        _NE + "10m_cultural/ne_10m_admin_0_countries.zip",
        "ce1ac7036499a0edd641fbc093cd209a98f96a49d2eca8480aaacad35138a7f6",
        "2022-05-08",
        "5.1.1",
        "Public domain",
        "https://www.naturalearthdata.com/about/terms-of-use/",
        "Made with Natural Earth.",
    ),
    Source(
        "admin1",
        _NE + "10m_cultural/ne_10m_admin_1_states_provinces.zip",
        "efc59726337323058f9446210adc96673179cd344e053666ee3d28cb58ba2b05",
        "2022-05-08",
        "5.1.1",
        "Public domain",
        "https://www.naturalearthdata.com/about/terms-of-use/",
        "Made with Natural Earth.",
    ),
    Source(
        "land",
        _NE + "10m_physical/ne_10m_land.zip",
        "e547d749445eaa0964aba76738090ec88f5e63c4585122170f98c67a7ea922dc",
        "2022-05-08",
        "5.1.1",
        "Public domain",
        "https://www.naturalearthdata.com/about/terms-of-use/",
        "Made with Natural Earth.",
    ),
    Source(
        "cities1000",
        "https://download.geonames.org/export/dump/cities1000.zip",
        "03a8fef1f34c0547183fc80b36dd552ae402531dc0656f7dd5d033e7712c9b05",
        "2026-10-01",
        "daily-2026-10-01",
        "CC BY 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        "GeoNames (geonames.org), CC BY 4.0.",
    ),
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def acquire(cache: Path) -> dict[str, Path]:
    cache.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for source in SOURCES:
        path = cache / f"{source.name}.zip"
        if not path.exists():
            temporary = path.with_suffix(".partial")
            try:
                with (
                    urllib.request.urlopen(source.url, timeout=120) as response,
                    temporary.open("wb") as out,
                ):
                    shutil.copyfileobj(response, out)
                check_archive(temporary, source)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        check_archive(path, source)
        result[source.name] = path
    return result


def check_archive(path: Path, source: Source) -> None:
    if sha256(path) != source.sha256:
        raise ValueError(
            f"SHA256 mismatch for {source.name}; obtain the pinned {source.date} "
            "archive. Upstream daily/latest URLs can change; "
            "pins are never refreshed automatically."
        )


def provenance() -> list[dict[str, str]]:
    return [asdict(source) for source in SOURCES]
