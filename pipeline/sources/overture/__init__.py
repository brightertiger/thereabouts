"""Overture source adapter."""

from pipeline.config.source_options import Divisions as Options
from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin

from ..proposals.overture import propose as propose_pin
from .normalize import normalize

__all__ = ["Options", "normalize", "propose"]


def propose(settings: SourceSettings) -> SourcePin:
    """Resolve upstream only for an explicit pin proposal."""
    return propose_pin(settings)
