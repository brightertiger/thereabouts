"""Acquire and broadly normalize GeoNames P/A points and multilingual aliases."""

from .geonames_download import download
from .geonames_normalize import normalize

__all__ = ["download", "normalize"]
