"""Public failures for pack discovery, integrity and lifecycle."""


class GeocoderError(Exception):
    """Base class for offline geocoder failures."""

    code = "geocoder_error"


class DataNotInstalledError(GeocoderError):
    """No data pack was selected or the selected directory does not exist."""

    code = "data_not_installed"


class UnsupportedSchemaError(GeocoderError):
    """The pack uses a schema this engine cannot read."""


class DamagedPackError(GeocoderError):
    """A pack has invalid metadata, structure, content or checksums."""


class ClosedGeocoderError(GeocoderError):
    """An operation was attempted after closing a geocoder."""

    code = "closed_geocoder"


class IncompatibleDataError(GeocoderError):
    """The selected pack requires a different reader or family."""

    code = "incompatible_data"


class CorruptPackError(GeocoderError):
    """A pack's checksum, record, or inventory failed validation."""

    code = "corrupt_pack"
