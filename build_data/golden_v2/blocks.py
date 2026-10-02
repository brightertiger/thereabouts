"""Expand original ancestors, normalize at r8 centres, then recompact exactly."""

from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from h3.api import basic_int as h3
from numpy.typing import NDArray

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, write_json
from build_data.cities.engine import Engine
from build_data.golden.cells import compact
from build_data.golden.reader import interval
from build_data.golden.schemas import CELLS
from build_data.golden.storage import budget, parquet
from build_data.hierarchy import descendants
from build_data.reconcile.common import Row

FIELDS = ("country_id", "state_id", "city_id", "city_method", "land_method")


def expand(record: Row) -> tuple[NDArray[np.uint64], NDArray[np.float64], list[Row]]:
    fine, coordinates = descendants(int(record["block"], 16), 8)
    labels = np.full(len(fine), -1, dtype=np.int64)
    rows = pq.read_table(record["path"]).to_pylist()
    for i, row in enumerate(rows):
        lo, hi = interval(row["h3_uint64"], row["h3_resolution"])
        a, b = np.searchsorted(fine, [lo, hi], side="left")
        b = int(np.searchsorted(fine, hi, side="right"))
        if (labels[a:b] >= 0).any():
            raise ValueError("Overlapping base ancestors")
        labels[a:b] = i
    return fine, coordinates, [rows[i] if i >= 0 else {} for i in labels]


def transform(
    record: Row, engines: dict[str, Engine], radius: bool
) -> tuple[list[Row], Row]:
    fine, coordinates, before = expand(record)
    answers = [tuple(row.get(k) for k in FIELDS) for row in before]
    after = list(answers)
    counts: dict[str, Row] = {}
    for cc, engine in engines.items():
        selected = np.array(
            [i for i, r in enumerate(before) if r.get("country_id") == f"country:{cc}"],
            dtype=np.int64,
        )
        if not len(selected):
            continue
        old_ids = np.array([before[i]["city_id"] for i in selected], dtype=object)
        old_methods = np.array(
            [before[i]["city_method"] for i in selected], dtype=object
        )
        ids, methods = engine.apply(
            coordinates[selected],
            old_ids,
            old_methods,
            radius,
            np.array([before[i].get("land_method") == "offshore" for i in selected]),
        )
        transitions: Counter[str] = Counter()
        for i, identity, method, old_method in zip(
            selected, ids, methods, old_methods, strict=True
        ):
            a = answers[i]
            after[i] = (a[0], a[1], identity, method, a[4])
            transitions[f"{old_method or 'null'} -> {method or 'null'}"] += 1
        counts[cc] = {
            "eligible": len(selected),
            "changed_city": int(np.count_nonzero(ids != old_ids)),
            "method_transitions": dict(transitions),
        }
    catalogue = {
        answer: i + 1
        for i, answer in enumerate(sorted(set(after) - {(None,) * 5}, key=str))
    }
    values = np.array([catalogue.get(a, 0) for a in after], dtype=np.uint64)
    stored, labels = compact(fine, values)
    by_code = {v: k for k, v in catalogue.items()}
    rows = []
    for cell, label in zip(stored, labels, strict=True):
        country_id, state, city, method, land = by_code[int(label)]
        rows.append(
            {
                "h3": h3.int_to_str(int(cell)),
                "h3_uint64": int(cell),
                "h3_resolution": h3.get_resolution(int(cell)),
                "country_id": country_id,
                "state_id": state,
                "city_id": city,
                "city_method": method,
                "country_method": "area" if country_id else None,
                "state_method": "area" if state else None,
                "land_method": land,
            }
        )
    if sum(h3.cell_to_children_size(r["h3_uint64"], 8) for r in rows) != sum(
        bool(r) for r in before
    ):
        raise ValueError("Normalization changed land eligibility")
    return rows, counts


def build(
    workspace: Workspace,
    output: Path,
    record: Row,
    engines: dict[str, Engine],
    identity: str,
    radius: bool,
) -> Row:
    root = record["block"]
    digest = fingerprint({"base": record, "normalization": identity, "radius": radius})
    receipt = output / "checkpoints" / f"{root}.json"
    ledger = Ledger(workspace.ledger_path)
    unit = str(output.resolve()) + ":" + root
    if ledger.is_complete("golden-v2.cells", unit, digest):
        return read_json(receipt)
    budget(workspace)
    rows, counts = transform(record, engines, radius)
    table = parquet(output / "cells" / f"{root}.parquet", rows, CELLS)
    table.update(kind="cells", block=root)
    result = {"table": table, "countries": counts}
    write_json(receipt, result)
    ledger.complete("golden-v2.cells", unit, digest, [Path(table["path"]), receipt])
    return result
