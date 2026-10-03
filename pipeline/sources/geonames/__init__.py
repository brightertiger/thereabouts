"""GeoNames source adapter."""

from pipeline.config.source_options import Names as Options

from .normalize import normalize

__all__ = ["Options", "normalize"]
