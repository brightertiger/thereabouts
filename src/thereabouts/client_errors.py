"""Input and resolution failures of the serving-pack API."""

from .errors import GeocoderError


class InvalidInputError(GeocoderError, ValueError):
    """An input cannot be interpreted under the requested resolver's contract."""


class AmbiguousResultError(GeocoderError):
    """More than one candidate remains; no selection is justified."""
