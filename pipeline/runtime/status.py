"""Summarize recorded completions and unique local output bytes without hashing."""

import json

from .ledger import Ledger
from .paths import located


def status(ledger: Ledger) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    seen: dict[str, set[str]] = {}
    for row in ledger.db.execute("SELECT stage,outputs FROM units ORDER BY stage"):
        stage = str(row["stage"])
        counts = result.setdefault(
            stage,
            {"units": 0, "recorded_bytes": 0, "local_bytes": 0, "missing_files": 0},
        )
        counts["units"] += 1
        paths = seen.setdefault(stage, set())
        for output in json.loads(row["outputs"]):
            name = str(output["path"])
            if name in paths:
                continue
            paths.add(name)
            counts["recorded_bytes"] += output["size"]
            if name.startswith("/"):
                from pipeline.migration.paths import legacy_relative

                name = legacy_relative(name, ledger.root)
            path = located(ledger.root, name)
            if path.is_file():
                counts["local_bytes"] += path.stat().st_size
            else:
                counts["missing_files"] += 1
    return result
