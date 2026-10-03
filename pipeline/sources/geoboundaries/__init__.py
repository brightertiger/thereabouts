"""geoBoundaries source adapter."""

from pipeline.config.source_options import Boundaries as Options

from .normalize import normalize

__all__ = ["Options", "normalize"]
