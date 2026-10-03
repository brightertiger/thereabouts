"""Overture source adapter."""

from pipeline.config.source_options import Divisions as Options

from .normalize import normalize

__all__ = ["Options", "normalize"]
