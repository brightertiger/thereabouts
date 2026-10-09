"""Checkpoint the country identity-link catalogue independently of assignment."""

from __future__ import annotations

from pathlib import Path

from pipeline.config.engines import EngineLimits
from pipeline.engines.store.codec import Row
from pipeline.engines.store.database import check_database, connect
from pipeline.runtime.jsonio import atomic_output

from .matching import link_divisions, prepare_catalog


def catalog(root: Path, output: Path, policy: Row, limits: EngineLimits) -> Path:
    with atomic_output(output) as temp:
        db = connect(temp, cache_kib=limits.sqlite_cache_kib)
        try:
            prepare_catalog(db, root, limits.source_batch_rows)
            link_divisions(db, root, policy, limits.source_batch_rows)
        finally:
            db.close()
        check_database(temp, limits.sqlite_cache_kib)
    return output
