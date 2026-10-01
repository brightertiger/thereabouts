"""Shared, offline-testable acquisition primitives; source adapters live alongside."""

from .download import download_file
from .io import atomic_output, fingerprint, sha256_file
from .ledger import Ledger
from .parquet import validate_parquet, write_partition
from .schemas import AREAS, NAMES, PLACES, SCHEMA_HASHES, SCHEMAS, validate_table
from .workspace import Workspace

__all__ = [
    "AREAS",
    "NAMES",
    "PLACES",
    "SCHEMAS",
    "SCHEMA_HASHES",
    "Ledger",
    "Workspace",
    "atomic_output",
    "download_file",
    "fingerprint",
    "sha256_file",
    "validate_parquet",
    "validate_table",
    "write_partition",
]
