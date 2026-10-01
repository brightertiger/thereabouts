"""Geonames index."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import cast

from . import Ledger, Workspace
from .geonames_download import SOURCE
from .geonames_rows import Row, alias, english_rank, place
from .geonames_tsv import chunks, lines
from .io import publish
from .runtime import source_budget


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro" if readonly else str(path), uri=readonly
    )
    db.execute("PRAGMA cache_size=-32768")
    db.execute("PRAGMA temp_store=FILE")
    if not readonly:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("PRAGMA synchronous=FULL")
        db.executescript(
            "CREATE TABLE IF NOT EXISTS features "
            "(id INTEGER PRIMARY KEY, offset INTEGER);"
            "CREATE TABLE IF NOT EXISTS aliases "
            "(id INTEGER PRIMARY KEY, offset INTEGER);"
            "CREATE TABLE IF NOT EXISTS english (id INTEGER PRIMARY KEY, name TEXT, "
            "rank INTEGER, alias_id INTEGER);"
            "CREATE TABLE IF NOT EXISTS done (unit TEXT PRIMARY KEY, counts TEXT);"
        )
    return db


def _index_place(
    db: sqlite3.Connection, raw: bytes, offset: int, release: str, pin: Row
) -> str:
    row = place(raw, release, pin)
    if row is None:
        return "excluded"
    cursor = db.execute(
        "INSERT OR IGNORE INTO features VALUES (?, ?)", (row["source_id"], offset)
    )
    return "kept" if cursor.rowcount else "duplicate"


def _index_alias(
    db: sqlite3.Connection, raw: bytes, offset: int, release: str, pin: Row
) -> str:
    row = alias(raw, release, pin)
    entity = str(row["entity_source_id"])
    if db.execute("SELECT 1 FROM features WHERE id=?", (entity,)).fetchone() is None:
        return "excluded"
    if not db.execute(
        "INSERT OR IGNORE INTO aliases VALUES (?, ?)", (row["source_id"], offset)
    ).rowcount:
        return "duplicate"
    rank = english_rank(row)
    if rank is not None:
        db.execute(
            "INSERT INTO english VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, rank=excluded.rank, alias_id=excluded.alias_id "
            "WHERE (excluded.rank, excluded.alias_id) < "
            "(english.rank, english.alias_id)",
            (entity, row["name"], *rank),
        )
    return "kept"


def build_index(
    workspace: Workspace, inputs: Mapping[str, Path], inventory: Row, digest: str
) -> Path:
    """Commit each input interval in SQLite; publish the index only when complete."""
    path = workspace.work / SOURCE / digest / "lookup.sqlite3"
    ledger = Ledger(workspace.ledger_path)
    if ledger.is_complete("geonames.index", "lookup", digest):
        return path
    source_budget(workspace, SOURCE, 1_000_000_000)
    part = path.with_suffix(".sqlite3.part")
    pins = cast(dict[str, Row], inventory["files"])
    with closing(_connect(part)) as db:
        for member, archive, parser in (
            ("allCountries.txt", "allCountries.zip", _index_place),
            ("alternateNamesV2.txt", "alternateNamesV2.zip", _index_alias),
        ):
            for chunk in chunks(inputs[member]):
                key = f"{member}:{chunk.start}-{chunk.end}"
                if db.execute("SELECT 1 FROM done WHERE unit=?", (key,)).fetchone():
                    continue
                source_budget(workspace, SOURCE, 150_000_000)
                counts: Counter[str] = Counter()
                with db:
                    for offset, raw in lines(inputs[member], chunk):
                        try:
                            state = parser(
                                db,
                                raw,
                                offset,
                                str(inventory["source_release"]),
                                pins[archive],
                            )
                        except (ValueError, UnicodeError, OverflowError):
                            state = "rejected"
                        counts[state] += 1
                    db.execute(
                        "INSERT INTO done VALUES (?, ?)", (key, json.dumps(counts))
                    )
                print(f"Indexed {key}: {dict(counts)}", flush=True)
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise ValueError("GeoNames lookup integrity check failed")
    publish(part, path)
    ledger.complete("geonames.index", "lookup", digest, [path])
    return path
