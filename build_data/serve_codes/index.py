"""Disk-backed observation postings; source row multiplicity is preserved."""

from collections.abc import Iterator

from build_data.serve.catalogue import CatalogueIndex
from build_data.serve.snapshot import BATCH_ROWS, Row, Snapshot
from thereabouts.packs.jsonio import canonical, parse

from . import candidates, catalogue, source


class CodeIndex:
    def __init__(self, index: CatalogueIndex, snapshot: Snapshot, family: str) -> None:
        self.catalogue = index
        self.snapshot = snapshot
        self.family = family
        self.db = index.db
        self.source_rows = self.unindexed_rows = 0
        self.db.executescript("""
            DROP TABLE IF EXISTS observations;
            DROP TABLE IF EXISTS postings;
            CREATE TABLE observations (
                ordinal INTEGER PRIMARY KEY, identity TEXT, payload TEXT
            );
            CREATE TABLE postings (key TEXT, ordinal INTEGER,
                PRIMARY KEY(key,ordinal)
            ) WITHOUT ROWID;
        """)

    def load(self, release: Row) -> None:
        sources = {
            (row["source"], row["release"]): row["license"]
            for row in release["sources"]
        }
        cells = source.cells(self.snapshot)
        for table, row in source.rows(self.snapshot, self.family):
            if sources.get((row["source"], row["source_release"])) != row["license"]:
                raise ValueError(
                    "Lookup observation lacks matching release attribution"
                )
            self.source_rows += 1
            keys = source.keys(row, self.family)
            observation = source.observation(row, table, cells, self.family)
            if not keys:
                self.unindexed_rows += 1
                continue
            self.db.execute(
                "INSERT INTO observations VALUES (?,?,?)",
                (
                    self.source_rows,
                    source.identity(row, self.family),
                    canonical(observation).decode(),
                ),
            )
            self.db.executemany(
                "INSERT INTO postings VALUES (?,?)",
                [(key, self.source_rows) for key in keys],
            )
            self.db.executemany(
                "INSERT OR IGNORE INTO needed VALUES (?)",
                [(ref,) for ref in observation["refs"] if ref is not None],
            )
            if self.source_rows % BATCH_ROWS == 0:
                self.db.commit()
        self.db.commit()
        cells.cache.clear()
        catalogue.load(self.catalogue, self.snapshot)

    def records(self) -> Iterator[tuple[str, Row]]:
        for (key,) in self.db.execute(
            "SELECT DISTINCT key FROM postings ORDER BY key COLLATE BINARY"
        ):
            observations = []
            for identity, body in self.db.execute(
                "SELECT o.identity,o.payload FROM observations o "
                "JOIN postings p USING(ordinal) WHERE p.key=?",
                (key,),
            ):
                row = parse(body)
                refs = self.catalogue.references(
                    {ref for ref in row["refs"] if ref is not None}
                )
                row["refs"] = [0 if ref is None else refs[ref] for ref in row["refs"]]
                observations.append((identity, row))
            yield (
                key,
                candidates.payload(
                    observations,
                    self.family,
                    self.snapshot.manifest["normalization"]["policy"],
                ),
            )
