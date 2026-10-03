"""Load only required catalogue rows and their transitive relationships."""

import pyarrow.parquet as pq

from pipeline.engines.serving.catalogue import CatalogueIndex, compact_place
from pipeline.engines.serving.snapshot import BATCH_ROWS, Snapshot
from pipeline.pack_format.jsonio import canonical
from pipeline.pack_format.layout import REFERENCE_FIELDS, UINT32_MAX


def load(index: CatalogueIndex, snapshot: Snapshot) -> None:
    db = index.db
    while True:
        pending = {
            row[0]
            for row in db.execute("SELECT id FROM needed EXCEPT SELECT id FROM places")
        }
        if not pending:
            break
        found = set()
        for table in snapshot.tables("places"):
            for batch in pq.ParquetFile(snapshot.file(table)).iter_batches(
                batch_size=BATCH_ROWS
            ):
                for row in batch.to_pylist():
                    if row["place_id"] not in pending:
                        continue
                    if row["place_id"] in found:
                        raise ValueError("Duplicate required golden place")
                    found.add(row["place_id"])
                    value = compact_place(row, table["path"])
                    db.execute(
                        "INSERT INTO places VALUES (?,?,?,?,?,?)",
                        (
                            row["place_id"],
                            canonical(value).decode(),
                            *(value[k] for k in REFERENCE_FIELDS),
                        ),
                    )
                    db.executemany(
                        "INSERT OR IGNORE INTO needed VALUES (?)",
                        [(value[k],) for k in REFERENCE_FIELDS if value[k] is not None],
                    )
        if found != pending:
            raise ValueError("Dangling required golden catalogue reference")
        db.commit()
    db.execute("CREATE TABLE ids (ref INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL)")
    db.execute("INSERT INTO ids(id) SELECT id FROM needed ORDER BY id COLLATE BINARY")
    db.commit()
    index.count = int(db.execute("SELECT count(*) FROM ids").fetchone()[0])
    if index.count > UINT32_MAX:
        raise ValueError("Catalogue exceeds uint32 references")
