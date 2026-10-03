"""Offline reverse geocoding backed by the shared Rust core."""

from .errors import (
    ClosedGeocoderError,
    CorruptPackError,
    DataNotInstalledError,
    GeocoderError,
    IncompatibleDataError,
)
from .geocoder import Geocoder, reverse
from .results import Result

__all__ = [
    "ClosedGeocoderError",
    "CorruptPackError",
    "DataNotInstalledError",
    "Geocoder",
    "GeocoderError",
    "IncompatibleDataError",
    "Result",
    "reverse",
]
