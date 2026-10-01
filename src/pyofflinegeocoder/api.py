"""Public lifecycle, scalar composition and lazy ordered iteration."""

import os
import threading
from collections.abc import Iterable, Iterator
from os import PathLike
from types import TracebackType

from .admin import AdminLookup
from .errors import ClosedGeocoderError
from .manifest import locate
from .models import DatasetInfo, PlaceStatus, ReverseResult
from .pack import Pack
from .places import PlaceLookup
from .validation import coordinate, options


class Geocoder:
    """Open an immutable local pack; build search indexes lazily on first use."""

    def __init__(self, data_path: str | PathLike[str] | None = None) -> None:
        self._lock = threading.RLock()
        self._pack = Pack(locate(data_path))
        self._admin = AdminLookup(self._pack)
        self._places = PlaceLookup(self._pack)
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise ClosedGeocoderError(
                "Geocoder is closed; construct a new Geocoder to reopen"
            )

    def reverse(
        self,
        lat: float,
        lon: float,
        *,
        include_place: bool = True,
        max_place_distance_km: float | None = 50.0,
    ) -> ReverseResult:
        """Return original-point administration and optional nearest settlement."""
        with self._lock:
            self._check_open()
            lat, lon = coordinate(lat, lon)
            cutoff = options(include_place, max_place_distance_km)
            country, admin1, land = self._admin.lookup(lat, lon)
            place = None
            status: PlaceStatus = "disabled"
            if include_place:
                if land == "unknown":
                    status = "no_coverage"
                elif land == "outside_mask":
                    status = "outside_land"
                else:
                    place, status = self._places.lookup(lat, lon, cutoff)
            manifest = self._pack.manifest
            return ReverseResult(
                lat,
                lon,
                country,
                admin1,
                place,
                status,
                land,
                manifest["snapshot_id"],
                manifest["policy_id"],
            )

    def reverse_many(
        self,
        coordinates: Iterable[tuple[float, float]],
        *,
        include_place: bool = True,
        max_place_distance_km: float | None = 50.0,
    ) -> Iterator[ReverseResult]:
        """Yield in order, consuming and validating one pair at a time."""
        with self._lock:
            self._check_open()
            options(include_place, max_place_distance_km)
        for pair in coordinates:
            try:
                lat, lon = pair
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "each coordinate must be a (latitude, longitude) pair"
                ) from exc
            yield self.reverse(
                lat,
                lon,
                include_place=include_place,
                max_place_distance_km=max_place_distance_km,
            )

    def info(self) -> DatasetInfo:
        """Return snapshot identity, coverage and source attribution."""
        with self._lock:
            self._check_open()
            return self._pack.info()

    def verify(self) -> None:
        """Verify all local checksums, text, geometry and settlement structures."""
        with self._lock:
            self._check_open()
            self._pack.verify()
            for index in (self._admin.country, self._admin.admin1, self._admin.land):
                index.tree()
            self._places.tree()

    def close(self) -> None:
        """Release indexes and mappings; repeated closes are harmless."""
        with self._lock:
            if not self._closed:
                self._admin.close()
                self._places.close()
                self._pack.close()
                self._closed = True

    def __enter__(self) -> "Geocoder":
        """Return this open geocoder for use in a context manager."""
        self._check_open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the geocoder when leaving a context manager."""
        self.close()


_default: Geocoder | None = None
_default_pid: int | None = None
_default_lock = threading.RLock()


def reverse(
    lat: float,
    lon: float,
    *,
    include_place: bool = True,
    max_place_distance_km: float | None = 50.0,
) -> ReverseResult:
    """Query a lazy process-local default pack selected by PYOFFLINEGEOCODER_DATA."""
    global _default, _default_pid
    with _default_lock:
        if _default is None or _default_pid != os.getpid():
            _default = Geocoder()
            _default_pid = os.getpid()
        return _default.reverse(
            lat,
            lon,
            include_place=include_place,
            max_place_distance_km=max_place_distance_km,
        )
