"""Typed forward verbs over family handles; matching policy stays in Rust."""

from collections.abc import Iterable
from typing import Any

from numpy.typing import NDArray

from .errors import ClosedGeocoderError
from .handles import Handles
from .results import Result


class ForwardQueries:
    def __init__(self, handles: Handles) -> None:
        self._handles = handles

    def _ensure_open(self) -> None:
        if self._handles.closed:
            raise ClosedGeocoderError("Geocoder is closed")

    def postal(
        self, code: str, *, country: str | None = None, evidence: bool = False
    ) -> Result:
        """Find a postal code within an explicitly named country."""
        self._ensure_open()
        return Result.from_dict(
            self._handles.get("postal").postal(
                code if isinstance(code, str) else "",
                country=country,
                evidence=evidence,
            )
        )

    def postal_columns(
        self, codes: Iterable[str], *, country: str | None = None
    ) -> dict[str, NDArray[Any]]:
        """Return columns, plus offsets and columns for ambiguous candidates."""
        self._ensure_open()
        return self._handles.get("postal").postal_columns(
            [code if isinstance(code, str) else "" for code in codes], country=country
        )

    def airport(
        self,
        code: str,
        *,
        scheme: str | None = None,
        country: str | None = None,
        evidence: bool = False,
    ) -> Result:
        """Find an airport by IATA/ICAO, or an explicitly selected code scheme."""
        self._ensure_open()
        return Result.from_dict(
            self._handles.get("airports").airport(
                code if isinstance(code, str) else "",
                scheme=scheme,
                country=country,
                evidence=evidence,
            )
        )

    def airport_columns(
        self,
        codes: Iterable[str],
        *,
        scheme: str | None = None,
        country: str | None = None,
    ) -> dict[str, NDArray[Any]]:
        """Return airport columns and ambiguous candidate columns."""
        self._ensure_open()
        return self._handles.get("airports").airport_columns(
            [code if isinstance(code, str) else "" for code in codes],
            scheme=scheme,
            country=country,
        )
