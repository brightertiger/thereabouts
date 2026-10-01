"""Cache exact finest-centre envelopes; plan entries never count as built cells."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from h3.api import basic_int as h3

from build_data.hierarchy import blocks, descendants
from build_data.reconcile.common import Row, encode

from .planning import Dependencies
from .windows import envelopes


class Plan:
    def __init__(self, path: Path, dependencies: Dependencies) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS blocks("
            "root TEXT PRIMARY KEY,bounds TEXT,countries TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS version(number INTEGER)")
        self.dependencies = dependencies

    def close(self) -> None:
        self.db.close()

    def create(self) -> None:
        existing = {
            r[0]: json.loads(r[1])
            for r in self.db.execute("SELECT root,bounds FROM blocks")
        }
        version = self.db.execute("SELECT number FROM version").fetchone()
        for number, root in enumerate(blocks()):
            key = h3.int_to_str(root)
            if key in existing and version == (3,):
                continue
            if key in existing and existing[key][2] - existing[key][0] <= 180:
                bounds = tuple(existing[key])
                regions = [bounds]
            else:
                _, points = descendants(root, 8)
                bounds = (
                    float(points[:, 1].min()),
                    float(points[:, 0].min()),
                    float(points[:, 1].max()),
                    float(points[:, 0].max()),
                )
                regions = envelopes(points)
            countries = sorted(
                {cc for region in regions for cc in self.dependencies.countries(region)}
            )
            self.db.execute(
                "INSERT OR REPLACE INTO blocks VALUES(?,?,?)",
                (key, encode(bounds), encode(countries)),
            )
            if number % 1000 == 0:
                self.db.commit()
                print(f"plan: {number + 1:,} exact block envelopes", flush=True)
        self.db.execute("DELETE FROM version")
        self.db.execute("INSERT INTO version VALUES(3)")
        self.db.commit()

    def rows(self, countries: list[str] | None = None) -> list[Row]:
        result = []
        for root, bounds, dependencies in self.db.execute(
            "SELECT * FROM blocks ORDER BY root"
        ):
            required = json.loads(dependencies)
            if countries and not set(countries).intersection(required):
                continue
            result.append(
                {"root": root, "bounds": json.loads(bounds), "countries": required}
            )
        return result
