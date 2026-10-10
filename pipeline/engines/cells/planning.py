"""Conservative country dependencies from all acquired country-area envelopes."""

from __future__ import annotations

import shapely
from shapely import STRtree

from pipeline.engines.store.codec import Row

from .windows import expanded


class Dependencies:
    def __init__(self, inventory: Row, offshore_m: float) -> None:
        self.codes = [r[0] for r in inventory["bounds"]]
        self.tree = STRtree([shapely.box(*r[1:]) for r in inventory["bounds"]])
        self.offshore_m = offshore_m

    def countries(self, bounds: tuple[float, float, float, float]) -> list[str]:
        result: set[str] = set()
        for w, e, s, n in expanded(bounds, self.offshore_m):
            result.update(
                self.codes[int(i)] for i in self.tree.query(shapely.box(w, s, e, n))
            )
        return sorted(result)
