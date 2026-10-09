"""Public failures for pack discovery, integrity and lifecycle."""


class GeocoderError(Exception):
    """Base class for offline geocoder failures."""

    code = "geocoder_error"


class DataNotInstalledError(GeocoderError):
    """No core pack is installed in the selected store."""

    code = "data_not_installed"


class ClosedGeocoderError(GeocoderError):
    """An operation was attempted after closing a geocoder."""

    code = "closed_geocoder"


class IncompatibleDataError(GeocoderError):
    """The selected pack requires a different reader or family."""

    code = "incompatible_data"


class CorruptPackError(GeocoderError):
    """A pack's checksum, record, or inventory failed validation."""

    code = "corrupt_pack"


class ResourceLimitError(GeocoderError, OSError):
    """The process ran out of file descriptors; raise the open-file limit."""

    code = "resource_limit"


class PackNotFoundError(GeocoderError, FileNotFoundError):
    """An explicitly selected pack directory does not exist."""

    code = "pack_not_found"


class WriterError(GeocoderError, ValueError):
    """A staging or output operation failed during dataset export."""

    code = "writer_error"


class WriterInputError(WriterError):
    """Dataset input, options or staging state prevents export."""

    code = "writer_input_error"
