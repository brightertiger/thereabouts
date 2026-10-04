"""Synchronous offline lookups with explicit coordinates and no downloads."""

from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from threading import Lock
from types import TracebackType
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray

from .forward_queries import ForwardQueries
from .handles import Handles
from .results import Result


class Coordinates(Protocol):
    """Named coordinate attributes accepted by reverse_many."""

    @property
    def lat(self) -> float: ...

    @property
    def lon(self) -> float: ...


class Geocoder(ForwardQueries):
    """Open selected families or discover installed packs from one dataset version.

    Forward families use the selected core's pinned catalogue for city detail and
    timezone. A standalone forward path retains source points and country/state
    context; city detail and timezone are null. Use packs to attach a core path.
    """

    def __init__(
        self,
        pack: str | Path | None = None,
        *,
        data_dir: str | Path | None = None,
        verify: bool = False,
        packs: Mapping[str, str | Path] | None = None,
    ) -> None:
        super().__init__(Handles(pack, packs, data_dir, verify))

    def reverse(self, *, lat: float, lon: float, evidence: bool = False) -> Result:
        """Return a flat result; invalid coordinates have status invalid_input."""
        self._ensure_open()
        if any(
            isinstance(v, (bool, np.bool_))
            or not isinstance(v, (int, float, np.integer, np.floating))
            for v in (lat, lon)
        ):
            return Result.from_dict(
                self._handles.get("core").reverse(float("nan"), 0.0)
            )
        return Result.from_dict(
            self._handles.get("core").reverse(lat, lon, evidence=evidence)
        )

    def from_h3(self, cell: str, *, evidence: bool = False) -> Result:
        """Find the stored ancestor of a valid H3 cell at resolution zero to eight."""
        self._ensure_open()
        return Result.from_dict(
            self._handles.get("core").from_h3(
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
        return self._handles.get("core").reverse_columns(
            np.asarray(lat, dtype=np.float64), np.asarray(lon, dtype=np.float64)
        )

    def close(self) -> None:
        """Release this handle; repeated close calls are harmless."""
        self._handles.close()

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
