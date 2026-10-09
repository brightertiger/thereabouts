"""Find superseded outputs and crash leftovers that no ledger record references."""

import json
import os
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath

from pipeline.config.schema import Config

from .jsonio import JSON
from .ledger import Ledger
from .outputs import HASHED


def embedded(value: JSON, root: Path) -> Iterator[str]:
    """Paths that manifests and receipts name, as workspace-relative strings."""
    if isinstance(value, list):
        for item in value:
            yield from embedded(item, root)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key != "path" or not isinstance(item, str):
                yield from embedded(item, root)
            elif not Path(item).is_absolute():
                yield item
            elif Path(item).is_relative_to(root):
                yield Path(item).relative_to(root).as_posix()


def references(ledger: Ledger) -> set[str]:
    """Recorded outputs, plus every file their JSON outputs point at.

    A consumer skipped by early cutoff keeps naming the upstream copy it was
    built from, so that copy stays until the consumer itself is rebuilt.
    """
    result: set[str] = set()
    for record in ledger.records():
        for output in record.outputs:
            result.add(output.path)
            path = ledger.root / output.path
            if not output.path.endswith(".json") or not path.is_file():
                continue
            try:
                value = json.loads(path.read_bytes())
            except ValueError:
                continue
            result.update(embedded(value, ledger.root))
    return result


def garbage(root: Path, config: Config, ledger: Ledger) -> list[Path]:
    """Inputs-hash directories holding no referenced file, orphan `.part` files,
    writer `.building` directories and DuckDB `spill` directories.

    Raw inputs are never candidates: content-addressed objects are kept, and
    their `.part` files hold resumable download progress.
    """
    live = {
        parent.as_posix()
        for name in references(ledger)
        for parent in PurePosixPath(name).parents
    }
    raw = Path(config.paths.raw).parts
    result = []
    for directory, folders, files in os.walk(root):
        here = Path(directory)
        relative = here.relative_to(root)
        if relative.parts[: len(raw)] == raw:
            folders.clear()
            continue
        for folder in sorted(folders):
            path = here / folder
            if path.is_symlink():
                continue
            if (
                folder.endswith(".building")
                or folder == "spill"
                or (
                    HASHED.fullmatch(folder)
                    and (relative / folder).as_posix() not in live
                )
            ):
                result.append(path)
                folders.remove(folder)
        result.extend(here / name for name in sorted(files) if name.endswith(".part"))
    return result


def size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def remove(paths: Sequence[Path]) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
