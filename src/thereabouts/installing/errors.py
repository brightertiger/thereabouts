"""Installer-only failures, separate from lookup/data integrity errors."""

from ..errors import GeocoderError


class InstallationError(GeocoderError):
    """An installation could not finish; its previously active pack is unchanged."""


class DownloadError(InstallationError):
    """A requested transfer failed or violated its pinned byte count."""
