"""Disk-backed reference closure and deterministic public-to-pack ID assignment."""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pyarrow.parquet as pq

from pipeline.config.engines import EngineLimits
from pipeline.pack_format.jsonio import canonical, parse
from pipeline.pack_format.layout import (
    REFERENCE_FIELDS,
    REQUIRED_TEXT,
    ROLES,
    TEXT_FIELDS,
    UINT32_MAX,
)

from .snapshot import BATCH_ROWS, Row, Snapshot


def compact_place(row: Row, table: str) -> Row:
    result = {k: row.get(k) for k in TEXT_FIELDS if k != "evidence"}
    if any(
        not isinstance(result[k], str) or not result[k]
        for k in REQUIRED_TEXT - {"evidence"}
    ):
        raise ValueError("Missing required golden place field")
    if result["role"] not in ROLES:
        raise ValueError("Unknown golden place role")
    evidence = {
        "golden_table": table,
        "source_ids": json.loads(row["source_ids"]),
        "name_provenance": json.loads(row["name_provenance"]),
    }
    result["evidence"] = canonical(evidence).decode("utf-8")
    result.update({k: row.get(k) for k in REFERENCE_FIELDS})
    result["country_id"] = "country:" + row["country_code"]
    return result


class CatalogueIndex:
    """SQLite bounds sorting and closure memory; it is never shipped to clients."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.count = 0
        self.db.execute(f"PRAGMA cache_size=-{EngineLimits.sqlite_cache_kib}")
        self.db.execute("PRAGMA temp_store=FILE")
        self.db.executescript("""
            DROP TABLE IF EXISTS places;
            DROP TABLE IF EXISTS needed;
            DROP TABLE IF EXISTS ids;
            CREATE TABLE places (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, country TEXT,
                parent TEXT, sovereign TEXT, normalized TEXT
            ) WITHOUT ROWID;
            CREATE TABLE needed (id TEXT PRIMARY KEY) WITHOUT ROWID;
        """)

    def load(self, snapshot: Snapshot) -> None:
        columns = sorted(
            (set(TEXT_FIELDS) - {"evidence"})
            | (set(REFERENCE_FIELDS) - {"country_id"})
            | {"source_ids", "name_provenance"}
        )
        for table in snapshot.tables("places"):
            for batch in pq.ParquetFile(snapshot.file(table)).iter_batches(
                batch_size=BATCH_ROWS, columns=columns
            ):
                entries = []
                for row in batch.to_pylist():
                    value = compact_place(row, table["path"])
                    entries.append(
                        (
                            row["place_id"],
                            canonical(value).decode("utf-8"),
                            *(value[k] for k in REFERENCE_FIELDS),
                        )
                    )
                self.db.executemany("INSERT INTO places VALUES (?,?,?,?,?,?)", entries)
            self.db.commit()
        for table in snapshot.tables("cells"):
            for batch in pq.ParquetFile(snapshot.file(table)).iter_batches(
                batch_size=BATCH_ROWS, columns=["country_id", "state_id", "city_id"]
            ):
                refs = {
                    (v,)
                    for col in batch.columns
                    for v in col.to_pylist()
                    if v is not None
                }
                self.db.executemany("INSERT OR IGNORE INTO needed VALUES (?)", refs)
            self.db.commit()
        while True:
            changed = self.db.total_changes
            for field in ("country", "parent", "sovereign", "normalized"):
                self.db.execute(f"""INSERT OR IGNORE INTO needed
                    SELECT p.{field} FROM places p JOIN needed n ON p.id=n.id
                    WHERE p.{field} IS NOT NULL""")
            self.db.commit()
            if changed == self.db.total_changes:
                break
        missing = self.db.execute(
            "SELECT n.id FROM needed n LEFT JOIN places p USING(id) "
            "WHERE p.id IS NULL LIMIT 1"
        ).fetchone()
        if missing:
            raise ValueError(f"Dangling golden reference: {missing[0]}")
        self.db.execute(
            "CREATE TABLE ids (ref INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL)"
        )
        self.db.execute(
            "INSERT INTO ids(id) SELECT id FROM needed ORDER BY id COLLATE BINARY"
        )
        self.db.commit()
        self.count = int(self.db.execute("SELECT count(*) FROM ids").fetchone()[0])
        if self.count > UINT32_MAX:
            raise ValueError("Catalogue exceeds uint32 ID capacity")

    def references(self, values: set[str]) -> dict[str, int]:
        result = {}
        for value in sorted(values):
            row = self.db.execute("SELECT ref FROM ids WHERE id=?", (value,)).fetchone()
            if row is None:
                raise ValueError(f"Unknown catalogue reference: {value}")
            result[value] = int(row[0])
        return result

    def records(self) -> Iterator[tuple[int, Row]]:
        query = """SELECT i.ref,p.payload,c.ref,a.ref,s.ref,n.ref FROM ids i
            JOIN places p USING(id)
            LEFT JOIN ids c ON c.id=p.country LEFT JOIN ids a ON a.id=p.parent
            LEFT JOIN ids s ON s.id=p.sovereign LEFT JOIN ids n ON n.id=p.normalized
            ORDER BY i.ref"""
        for row in self.db.execute(query):
            value = parse(row[1])
            value.update(
                zip(
                    REFERENCE_FIELDS,
                    (int(v) if v is not None else 0 for v in row[2:]),
                    strict=True,
                )
            )
            yield int(row[0]), value

    def close(self) -> None:
        self.db.close()
