"""Public failures for pack discovery, integrity and lifecycle."""


class GeocoderError(Exception):
    """Base class for offline geocoder failures."""


class DataNotInstalledError(GeocoderError):
    """No data pack was selected or the selected directory does not exist."""


class UnsupportedSchemaError(GeocoderError):
    """The pack uses a schema this engine cannot read."""


class DamagedPackError(GeocoderError):
    """A pack has invalid metadata, structure, content or checksums."""


class ClosedGeocoderError(GeocoderError):
    """An operation was attempted after closing a geocoder."""
