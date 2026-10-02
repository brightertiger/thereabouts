"""Local table lifecycle and bounded, vectorized query batches."""

import copy
import os
import threading
from collections.abc import Iterable, Iterator
from itertools import islice
from os import PathLike
from types import TracebackType
from typing import Any

import numpy as np
from h3.api import basic_int as h3

from .errors import ClosedGeocoderError
from .manifest import locate
from .models import Location
from .table import Table
from .validation import coordinate


class Geocoder:
    """Memory-map an immutable H3 table directory without network access."""

    def __init__(self, data_path: str | PathLike[str] | None = None) -> None:
        self._lock = threading.RLock()
        self._table = Table(locate(data_path))
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise ClosedGeocoderError("Geocoder is closed; create a new instance")

    def reverse(self, lat: float, lon: float) -> Location | None:
        """Look up the table's finest H3 cell containing the input point."""
        with self._lock:
            self._check_open()
            lat, lon = coordinate(lat, lon)
            cell = h3.latlng_to_cell(lat, lon, self._table.resolution)
            return self._table.lookup_one(cell)

    def reverse_many(
        self, coordinates: Iterable[tuple[float, float]]
    ) -> Iterator[Location | None]:
        """Yield in order, validating and searching at most 4096 pairs ahead."""
        iterator = iter(coordinates)
        while True:
            with self._lock:
                self._check_open()
                pairs = list(islice(iterator, 4096))
                if not pairs:
                    return
                cells = []
                for pair in pairs:
                    try:
                        lat, lon = pair
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            "each coordinate must be a (lat, lon) pair"
                        ) from exc
                    lat, lon = coordinate(lat, lon)
                    cells.append(h3.latlng_to_cell(lat, lon, self._table.resolution))
                results = self._table.lookup(np.asarray(cells, dtype=np.uint64))
            for result in results:
                # Buffered Locations own no mmap views. Only the closed flag
                # matters here; retain immediate iterator invalidation.
                if self._closed:
                    self._check_open()
                yield result

    def info(self) -> dict[str, Any]:
        """Return a detached copy of the manifest, including attribution."""
        with self._lock:
            self._check_open()
            return copy.deepcopy(self._table.manifest)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._table.close()
                self._closed = True

    def __enter__(self) -> "Geocoder":
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


_default: Geocoder | None = None
_default_pid: int | None = None
_default_lock = threading.RLock()


def reverse(lat: float, lon: float) -> Location | None:
    """Use the process-local table selected by THEREABOUTS_DATA."""
    global _default, _default_pid
    with _default_lock:
        if _default is None or _default_pid != os.getpid():
            _default = Geocoder()
            _default_pid = os.getpid()
        return _default.reverse(lat, lon)
