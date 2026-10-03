"""Plate evidence source adapter."""

from pipeline.config.source_options import Plates as Options

from .normalize import normalize

__all__ = ["Options", "normalize"]
