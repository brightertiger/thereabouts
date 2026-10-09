from typing import Any

import numpy as np
from numpy.typing import NDArray

MAX_ARCHIVE_BYTES: int
MAX_UNPACKED_BYTES: int
DEFAULT_RELEASE_URL: str
INDEX_FORMAT: int
ARCHIVE_SUFFIX: str

class Geocoder:
    def reverse(
        self, lat: float, lon: float, *, evidence: bool = False
    ) -> dict[str, Any]: ...
    def from_h3(self, cell: str, *, evidence: bool = False) -> dict[str, Any]: ...
    def reverse_columns(
        self, lat: NDArray[np.float64], lon: NDArray[np.float64]
    ) -> dict[str, NDArray[Any]]: ...
    def postal(
        self, code: str, *, country: str | None = None, evidence: bool = False
    ) -> dict[str, Any]: ...
    def postal_columns(
        self, codes: list[str], *, country: str | None = None
    ) -> dict[str, NDArray[Any]]: ...
    def airport(
        self,
        code: str,
        *,
        scheme: str | None = None,
        country: str | None = None,
        evidence: bool = False,
    ) -> dict[str, Any]: ...
    def airport_columns(
        self, codes: list[str], *, scheme: str | None = None, country: str | None = None
    ) -> dict[str, NDArray[Any]]: ...
    def locode(
        self, code: str, *, country: str | None = None, evidence: bool = False
    ) -> dict[str, Any]: ...
    def locode_columns(
        self, codes: list[str], *, country: str | None = None
    ) -> dict[str, NDArray[Any]]: ...
    def phone(
        self, number: str, *, country: str | None = None, evidence: bool = False
    ) -> dict[str, Any]: ...
    def phone_columns(self, numbers: list[str]) -> dict[str, NDArray[Any]]: ...
    def ip(self, address: str, *, evidence: bool = False) -> dict[str, Any]: ...
    def ip_columns(self, addresses: list[str]) -> dict[str, NDArray[Any]]: ...
    def plate(
        self,
        value: str,
        *,
        country: str | None = None,
        series: str | None = None,
        evidence: bool = False,
    ) -> dict[str, Any]: ...
    def plate_columns(
        self,
        values: list[str],
        *,
        country: str | None = None,
        series: str | None = None,
    ) -> dict[str, NDArray[Any]]: ...
    def geocode(
        self,
        name: str,
        *,
        country: str | None = None,
        subdivision: str | None = None,
        limit: int = 5,
        prefer: str | None = None,
        scope: str = "cities",
        evidence: bool = False,
    ) -> dict[str, Any]: ...
    def geocode_columns(
        self,
        names: list[str],
        *,
        country: str | None = None,
        subdivision: str | None = None,
        limit: int = 5,
        prefer: str | None = None,
        scope: str = "cities",
    ) -> dict[str, NDArray[Any]]: ...
    def close(self) -> None: ...

def open(
    path: str,
    *,
    verify: bool = False,
    core: Geocoder | None = None,
    max_open_files: int | None = None,
) -> Geocoder: ...
def write_pack(
    dataset_dir: str, family: str, output_dir: str, options: dict[str, Any]
) -> dict[str, Any]: ...
def verify_pack(path: str) -> dict[str, Any]: ...
def pack_info(path: str) -> dict[str, Any]: ...
def data_directory(explicit: str | None = None) -> str: ...
def installed_pack(root: str, family: str) -> str: ...
def run_cli(argv: list[str] | None = None) -> int: ...
def platform_directory(platform: str) -> str: ...
