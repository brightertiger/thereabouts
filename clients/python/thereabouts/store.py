"""Persistent pack locations and read-only selection of an active installation."""

from pathlib import Path

from .errors import DataNotInstalledError


def data_directory(explicit: str | Path | None = None) -> Path:
    """Use the native store's precedence and platform policy for every caller."""
    from . import _core

    try:
        return Path(
            _core.data_directory(str(explicit) if explicit is not None else None)
        )
    except ValueError as exc:
        raise DataNotInstalledError("thereabouts data install core") from exc


def active_pack(data_dir: str | Path | None = None, *, family: str = "core") -> Path:
    """Discover the pinned dataset using the shared native store policy."""
    from . import _core

    try:
        root = data_directory(data_dir).resolve()
    except DataNotInstalledError as exc:
        raise DataNotInstalledError(f"thereabouts data install {family}") from exc
    return Path(_core.installed_pack(str(root), family))
