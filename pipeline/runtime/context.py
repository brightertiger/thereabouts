"""Construct the shared stage context from explicit runtime dependencies."""

from pathlib import Path

from pipeline.config import Config
from pipeline.stages.contract import Context

from .ledger import Ledger
from .resources import ResourceGuard
from .verification import Verifier


def context(config: Config, root: Path, ledger: Ledger) -> Context:
    return Context(
        config,
        root,
        ledger,
        ResourceGuard(root, config.resources),
        Verifier(root),
        storage=config.storage,
    )
