"""Geoboundaries config."""

from __future__ import annotations

from http.client import HTTPException
from typing import Any

SOURCE = "geoboundaries"

API = "https://www.geoboundaries.org/api/current/gbOpen"

REPO_API = "https://api.github.com/repos/wmgeolab/geoBoundaries"

MEDIA = "https://media.githubusercontent.com/media/wmgeolab/geoBoundaries"


DOWNLOAD_VERSION = "1"

ADM2_COUNTRIES = ("PHL",)

HEADERS = {"Accept-Encoding": "identity", "User-Agent": "Thereabouts/acquire"}

RETRY_ERRORS = (OSError, HTTPException)


def _unit(layer: dict[str, Any]) -> str:
    return f"{layer['boundaryISO']}-{layer['boundaryType']}"
