"""OSM land source adapter."""

from pipeline.config.source_options import Land as Options

from .normalize import normalize

__all__ = ["Options", "normalize"]
