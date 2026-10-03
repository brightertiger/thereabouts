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

    def locode(
        self, code: str, *, country: str | None = None, evidence: bool = False
    ) -> Result:
        """Find a locode code within an explicitly named country."""
        self._ensure_open()
        return Result.from_dict(
            self._handles.get("locode").locode(
                code if isinstance(code, str) else "",
                country=country,
                evidence=evidence,
            )
        )

    def locode_columns(
        self, codes: Iterable[str], *, country: str | None = None
    ) -> dict[str, NDArray[Any]]:
        """Return columns, plus offsets and columns for ambiguous candidates."""
        self._ensure_open()
        return self._handles.get("locode").locode_columns(
            [code if isinstance(code, str) else "" for code in codes], country=country
        )

    def phone(self, number: str, *, evidence: bool = False) -> Result:
        """Find the longest published prefix of an international E.164 number."""
        self._ensure_open()
        return Result.from_dict(
            self._handles.get("phone").phone(
                number if isinstance(number, str) else "",
                evidence=evidence,
            )
        )

    def phone_columns(self, numbers: Iterable[str]) -> dict[str, NDArray[Any]]:
        """Return phone prefix columns and ambiguous country candidates."""
        self._ensure_open()
        return self._handles.get("phone").phone_columns(
            [number if isinstance(number, str) else "" for number in numbers]
        )

    def ip(self, address: str, *, evidence: bool = False) -> Result:
        """Find the published interval containing an IPv4 or IPv6 address."""
        self._ensure_open()
        return Result.from_dict(
            self._handles.get("ip").ip(
                address if isinstance(address, str) else "",
                evidence=evidence,
            )
        )

    def ip_columns(self, addresss: Iterable[str]) -> dict[str, NDArray[Any]]:
        """Return ip interval columns."""
        self._ensure_open()
        return self._handles.get("ip").ip_columns(
            [address if isinstance(address, str) else "" for address in addresss]
        )
