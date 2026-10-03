"""Public failures for pack discovery, integrity and lifecycle."""


class GeocoderError(Exception):
    """Base class for offline geocoder failures."""

    code = "geocoder_error"


class DataNotInstalledError(GeocoderError):
    """No core pack is installed in the selected store."""

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


class PackNotFoundError(GeocoderError, FileNotFoundError):
    """An explicitly selected pack directory does not exist."""

    code = "pack_not_found"


class WriterError(GeocoderError, ValueError):
    """A staging or output operation failed during dataset export."""

    code = "writer_error"


class WriterInputError(WriterError):
    """Dataset input, options or staging state prevents export."""

    code = "writer_input_error"
