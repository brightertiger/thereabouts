"""One verified, atomic Parquet per resolution-3 subtree, including empty ocean."""

from __future__ import annotations

import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import numpy as np
from h3.api import basic_int as h3
from numpy.typing import NDArray

from build_data.acquire import Ledger, Workspace
from build_data.acquire.io import fingerprint, sha256_file
from build_data.hierarchy import descendants, groups, label_block
from build_data.reconcile.common import Row
from build_data.reconcile.lookup import Locator

from .inputs import Inputs
from .schemas import CELLS
from .seam import oracle as make_oracle
from .storage import budget, parquet


def builder() -> str:
    directory = Path(__file__).parent
    modules = [
        directory / name
        for name in (
            "cells.py",
            "geometry.py",
            "nearest.py",
            "oracle.py",
            "offshore.py",
            "seam.py",
            "windows.py",
        )
    ]
    modules.extend(
        (
            directory.parent / "hierarchy.py",
            directory.parent / "reconcile/classification.py",
            directory.parent / "reference/sphere.py",
            directory.parents[1] / "src/pyofflinegeocoder/format.py",
        )
    )
    return fingerprint(
        {
            "schema": str(CELLS),
            "code": {
                str(p.relative_to(directory.parents[1])): sha256_file(p)
                for p in modules
            },
            "libraries": {
                name: version(name)
                for name in ("h3", "numpy", "shapely", "scipy", "pyarrow")
            },
        }
    )


def compact(
    cells: NDArray[np.uint64], labels: NDArray[np.uint64]
) -> tuple[NDArray[np.uint64], NDArray[np.uint64]]:
    pending = np.ones(len(cells), dtype=bool)
    stored: list[int] = []
    values: list[np.uint64] = []
    for level in range(3, 9):
        starts, sizes = groups(cells, level)
        low, high = (
            np.minimum.reduceat(labels, starts),
            np.maximum.reduceat(labels, starts),
        )
        uniform = pending[starts] & (low == high)
        chosen = uniform & (low != 0)
        stored.extend(h3.cell_to_parent(int(c), level) for c in cells[starts[chosen]])
        values.extend(low[chosen])
        pending[np.repeat(uniform, sizes)] = False
        if not pending.any():
            break
    return np.array(stored, dtype=np.uint64), np.array(values, dtype=np.uint64)


def digest(inputs: Inputs, countries: list[str], implementation: str) -> str:
    return fingerprint(
        {
            "land": inputs.land,
            "countries": {cc: inputs.countries[cc] for cc in countries},
            "policy": inputs.policy,
            "builder": implementation,
        }
    )


def build(
    workspace: Workspace,
    root: int,
    inputs: Inputs,
    countries: list[str],
    implementation: str,
    *,
    exhaustive: bool = False,
    scalar_samples: int = 0,
) -> Row:
    if not set(countries) <= inputs.countries.keys():
        raise ValueError("A block touching an unfinished country must wait")
    budget(workspace)
    started = time.monotonic()
    fine, coordinates = descendants(root, 8)
    paths = {cc: inputs.paths[cc] for cc in countries}
    with Locator(paths, Path(inputs.land["path"]), inputs.policy) as locator:
        oracle = make_oracle(locator, paths, coordinates)
        prepared = time.monotonic()
        labels = label_block(oracle, fine, coordinates, 8)
        labelled_at = time.monotonic()
        labelled = oracle.labelled_points
        stored, values = compact(fine, labels)
        production_seconds = time.monotonic() - started
        checks: Row = {}
        if exhaustive:
            direct = oracle.labels(coordinates)
            if not np.array_equal(labels, direct):
                bad = np.flatnonzero(labels != direct)
                raise ValueError(
                    f"Certificate mismatch in {h3.int_to_str(root)}: "
                    f"{len(bad)} centres, first={coordinates[bad[0]]}"
                )
            ancestor_table = {
                int(c): int(v) for c, v in zip(stored, values, strict=True)
            }
            for cell, expected in zip(fine, direct, strict=True):
                matches = [
                    ancestor_table[p]
                    for level in range(3, 9)
                    if (p := h3.cell_to_parent(int(cell), level)) in ancestor_table
                ]
                if matches != ([int(expected)] if expected else []):
                    raise ValueError("Compacted ancestor equivalence failed")
            checks["exhaustive_centres"] = len(fine)
        if scalar_samples:
            chosen = np.linspace(
                0, len(fine) - 1, min(scalar_samples, len(fine)), dtype=int
            )
            for i in chosen:
                answer = locator.locate(*coordinates[i])
                actual = oracle.answers[int(labels[i])]
                expected = (
                    *(
                        (answer[k] or {}).get("id")
                        for k in ("country", "state", "city")
                    ),
                    answer["city_method"],
                    answer["land_method"],
                )
                if actual != expected:
                    raise ValueError(
                        f"Scalar mismatch at {coordinates[i]}: {actual} != {expected}"
                    )
            checks["scalar_centres"] = len(chosen)
        output_rows = []
        resolutions: Counter[str] = Counter()
        for cell, value in zip(stored, values, strict=True):
            cc, state, city, method, land = oracle.answers[int(value)]
            resolution = h3.get_resolution(int(cell))
            resolutions[str(resolution)] += 1
            output_rows.append(
                {
                    "h3": h3.int_to_str(int(cell)),
                    "h3_uint64": int(cell),
                    "h3_resolution": resolution,
                    "country_id": cc,
                    "state_id": state,
                    "city_id": city,
                    "country_method": "area" if cc else None,
                    "state_method": "area" if state else None,
                    "city_method": method,
                    "land_method": land,
                }
            )
    path = workspace.root / "golden" / "cells" / f"{h3.int_to_str(root)}.parquet"
    table = parquet(path, output_rows, CELLS)
    stats = {
        "table": {**table, "kind": "cells", "block": h3.int_to_str(root)},
        "countries": countries,
        "enumerated": len(fine),
        "labelled": labelled,
        "eligible": int(np.count_nonzero(labels)),
        "seconds": time.monotonic() - started,
        "prepare_seconds": prepared - started,
        "label_seconds": labelled_at - prepared,
        "production_seconds": production_seconds,
        "resolutions": dict(resolutions),
        "checks": checks,
    }
    Ledger(workspace.ledger_path).complete(
        "golden.cells",
        h3.int_to_str(root),
        digest(inputs, countries, implementation),
        [path],
        metadata=stats,
    )
    return stats
