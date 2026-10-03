"""Rebuild bounded GeoNames identity and English-name indexes before normalization."""

import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from pipeline.runtime.jsonio import atomic_output
from pipeline.sources.contract import SourceContext

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
    target = ctx.work / ctx.unit.inputs_hash / "lookup.sqlite3"
    ctx.ensure(target)
    options = ctx.settings.options
    reservation = int(options["index_bytes"])
    ctx.runtime.guard.admit(reservation)
    written = 0
    try:
        with (
            atomic_output(target) as temporary,
            closing(sqlite3.connect(temporary)) as db,
        ):
            db.execute(f"PRAGMA cache_size=-{int(options['sqlite_cache_kib'])}")
            db.execute("PRAGMA temp_store=FILE")
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
                    ctx.runtime.guard.admit()
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
                    if temporary.stat().st_size > reservation:
                        raise ValueError(
                            "GeoNames index exceeds configured index_bytes"
                        )
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ValueError("GeoNames index integrity check failed")
        written = target.stat().st_size
        return target
    finally:
        ctx.runtime.guard.release(reservation, written_bytes=written)
