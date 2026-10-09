"""Rebuild bounded GeoNames identity and English-name indexes before normalization."""

import json
import sqlite3
from collections import Counter
from pathlib import Path

from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.scratch import scratch_index

from .inputs import evidence
from .rows import Row, alias, english_rank, place
from .tsv import chunks, lines


def index_place(
    db: sqlite3.Connection, raw: bytes, offset: int, release: str, pin: Row
) -> str:
    row = place(raw, release, pin)
    if row is None:
        return "excluded"
    cursor = db.execute(
        "INSERT OR IGNORE INTO features VALUES (?, ?)", (row["source_id"], offset)
    )
    return "kept" if cursor.rowcount else "duplicate"


def index_alias(
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


def build_index(ctx: SourceContext, inputs: dict[str, Path]) -> Path:
    options = ctx.settings.options
    with scratch_index(
        ctx,
        "lookup.sqlite3",
        int(options["index_bytes"]),
        label="GeoNames",
        check="integrity_check",
        cache_kib=int(options["sqlite_cache_kib"]),
    ) as index:
        db = index.db
        db.executescript(
            "CREATE TABLE features (id INTEGER PRIMARY KEY, offset INTEGER);"
            "CREATE TABLE aliases (id INTEGER PRIMARY KEY, offset INTEGER);"
            "CREATE TABLE english (id INTEGER PRIMARY KEY, name TEXT, "
            "rank INTEGER, alias_id INTEGER);"
            "CREATE TABLE done (unit TEXT PRIMARY KEY, counts TEXT);"
        )
        for member, archive, parser in (
            ("allCountries.txt", "allCountries.zip", index_place),
            ("alternateNamesV2.txt", "alternateNamesV2.zip", index_alias),
        ):
            pin = evidence(ctx, ctx.named(archive))
            for chunk in chunks(
                inputs[member],
                ctx.settings.limits.chunk_bytes,
                int(options["line_bytes"]),
            ):
                ctx.guard.admit()
                counts: Counter[str] = Counter()
                with db:
                    for offset, raw in lines(
                        inputs[member], chunk, int(options["line_bytes"])
                    ):
                        try:
                            state = parser(db, raw, offset, ctx.pin.release, pin)
                        except (ValueError, UnicodeError, OverflowError):
                            state = "rejected"
                        counts[state] += 1
                    db.execute(
                        "INSERT INTO done VALUES (?,?)",
                        (f"{member}:{chunk.start}-{chunk.end}", json.dumps(counts)),
                    )
                index.check_size()
    return index.path
