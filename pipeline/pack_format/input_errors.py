"""Input and resolution failures of the serving-pack API."""

from pipeline.geometry.errors import GeocoderError


class InvalidInputError(GeocoderError, ValueError):
    """An input cannot be interpreted under the requested resolver's contract."""


class AmbiguousResultError(GeocoderError):
    """More than one candidate remains; no selection is justified."""


class ContextRequiredError(InvalidInputError):
    """A code resolver needs an explicit country or identifier scheme."""


class IncompatibleDataError(GeocoderError):
    """Selected packs do not share a compatible catalogue and golden snapshot."""
