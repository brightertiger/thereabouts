"""Read-only permission checks before migration creates its first file."""

import os
import shlex
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from pipeline.runtime.jsonio import Object, read_object
from pipeline.runtime.paths import located

from .adoption import Migration


def blocked_directories(targets: Sequence[Path]) -> list[Path]:
    directories = set()
    for target in targets:
        directory = target.parent
        while not directory.exists():
            directory = directory.parent
        if not directory.is_dir():
            raise ValueError(f"Target parent is not a directory: {directory}")
        if not directory.stat().st_mode & stat.S_IWUSR or not os.access(
            directory, os.W_OK | os.X_OK
        ):
            directories.add(directory)
    return sorted(directories)


def check_writable(targets: Sequence[Path]) -> None:
    blocked = blocked_directories(targets)
    if not blocked:
        return
    enable = [f"chmod u+w {shlex.quote(str(path))}" for path in blocked]
    restore = [f"chmod a-w {shlex.quote(str(path))}" for path in blocked]
    raise ValueError(
        "Migration targets are read-only; no files were changed.\n"
        "Enable these directories for application:\n"
        + "\n".join(enable)
        + "\nRestore directory protection after verification:\n"
        + "\n".join(restore)
    )


def apply_targets(migration: Migration, target: Path) -> list[Path]:
    ctx = migration.context
    work = located(ctx.root, ctx.config.paths.work)
    return [
        target,
        work / "pipeline.lock",
        work / "ledger.pre-migration.sqlite3",
        work / "migration/pending.json",
        *[located(ctx.root, name) for name in migration.rewrites.after],
        *[
            located(work / "migration/before", name)
            for name in migration.rewrites.before
        ],
    ]


def recovery_targets(root: Path, work: Path) -> list[Path]:
    journal = work / "migration/pending.json"
    if not journal.exists():
        return []
    record = read_object(journal)
    return [
        journal,
        work / "pipeline.lock",
        *[
            located(root, str(item["path"]))
            for item in cast(list[Object], record["files"])
        ],
    ]
