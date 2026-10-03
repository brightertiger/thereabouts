"""Failures specific to immutable serving packs."""

from thereabouts.errors import GeocoderError


class CorruptPackError(GeocoderError):
    """A serving pack violates its checksum or structural contract."""


class UnsupportedPackError(GeocoderError):
    """A pack requires a format or feature this reader does not implement."""
