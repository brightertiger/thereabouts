"""Synchronous offline lookups with explicit coordinates and no downloads."""

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from . import _core
from .errors import ClosedGeocoderError
from .results import Result
from .store import core_pack


class Coordinates(Protocol):
    """Named coordinate attributes accepted by reverse_many."""

    @property
    def lat(self) -> float: ...

    @property
    def lon(self) -> float: ...


class Geocoder:
    """Open a core pack, or discover an installed pack in the existing store."""

    def __init__(
        self,
        pack: str | Path | None = None,
        *,
        data_dir: str | Path | None = None,
        verify: bool = False,
    ) -> None:
        if pack is not None and data_dir is not None:
            raise ValueError("Select pack or data_dir, not both")
        self._reader = _core.open(
            str(pack if pack is not None else core_pack(data_dir)), verify=verify
        )
        self._closed = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise ClosedGeocoderError("Geocoder is closed")

    def reverse(self, *, lat: float, lon: float, evidence: bool = False) -> Result:
        """Return a flat result; invalid coordinates have status invalid_input."""
        self._ensure_open()
        if any(
            isinstance(v, (bool, np.bool_))
            or not isinstance(v, (int, float, np.integer, np.floating))
            for v in (lat, lon)
        ):
            return Result.from_dict(self._reader.reverse(float("nan"), 0.0))
        return Result.from_dict(self._reader.reverse(lat, lon, evidence=evidence))

    def from_h3(self, cell: str, *, evidence: bool = False) -> Result:
        """Find the stored ancestor of a valid H3 cell at resolution zero to eight."""
        self._ensure_open()
        return Result.from_dict(
            self._reader.from_h3(
                cell if isinstance(cell, str) else "", evidence=evidence
            )
        )

    def reverse_many(
        self,
        points: Iterable[Mapping[str, float] | Coordinates],
        *,
        evidence: bool = False,
    ) -> Iterator[Result]:
        """Yield named mappings or coordinate objects in order; reject bare tuples."""
        self._ensure_open()
        for point in points:
            self._ensure_open()
            try:
                if isinstance(point, Mapping):
                    lat, lon = point["lat"], point["lon"]
                else:
                    lat, lon = point.lat, point.lon
            except (KeyError, AttributeError) as exc:
                raise TypeError(
                    "Each point must have named lat and lon fields"
                ) from exc
            yield self.reverse(lat=lat, lon=lon, evidence=evidence)

    def reverse_columns(
        self, lat: NDArray[Any], lon: NDArray[Any]
    ) -> dict[str, NDArray[Any]]:
        """Return dictionary string codes/categories and numeric *_valid masks."""
        self._ensure_open()
        if lat.ndim != 1 or lon.ndim != 1:
            raise ValueError("lat and lon must be one-dimensional")
        if lat.dtype.kind not in "ifu" or lon.dtype.kind not in "ifu":
            raise TypeError("lat and lon must have numeric, non-boolean dtypes")
        return self._reader.reverse_columns(
            np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
        )

    def close(self) -> None:
        """Release this handle; repeated close calls are harmless."""
        self._reader.close()
        self._closed = True

    def __enter__(self) -> "Geocoder":
        self._ensure_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


_default: Geocoder | None = None
_default_lock = Lock()


def reverse(*, lat: float, lon: float, evidence: bool = False) -> Result:
    """Lazily open the default installed core pack, without network access."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = Geocoder()
    return _default.reverse(lat=lat, lon=lon, evidence=evidence)
