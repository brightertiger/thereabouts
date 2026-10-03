"""Typed configuration, validated before opening a workspace for writing."""

from .loader import load
from .schema import Config

__all__ = ["Config", "load"]
