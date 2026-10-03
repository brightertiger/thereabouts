"""Compare re-reconciled countries at the same r8 centres as a saved golden baseline."""

from __future__ import annotations

import h3

from pipeline.engines.reconcile.common import Row
from pipeline.engines.reconcile.lookup import Locator


class CentreReader:
    """Use the independent scalar oracle, without building or changing cells."""

    def __init__(self, locator: Locator) -> None:
        self.locator = locator

    def lookup(self, cell: str | None) -> Row:
        if cell is None:
            return {"cell_status": "unlocated"}
        if h3.get_resolution(cell) != 8:
            raise ValueError("Expected a resolution-8 centre")
        answer = self.locator.locate(*h3.cell_to_latlng(cell))
        return {
            **{
                role + "_id": (answer[role] or {}).get("id")
                for role in ("country", "state", "city")
            },
            "city_method": answer["city_method"],
            "land_method": answer["land_method"],
            "cell_status": "matched"
            if answer["country"]
            else "unassigned"
            if answer["eligible"]
            else "ineligible",
        }
