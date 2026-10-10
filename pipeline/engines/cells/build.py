"""One verified, atomic Parquet per resolution-3 subtree, including empty ocean."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import numpy as np
from h3.api import basic_int as h3

from pipeline.engines.hierarchy import descendants, label_block
from pipeline.engines.reconcile.lookup import Locator
from pipeline.engines.store.codec import Row

from .compaction import compact
from .inputs import Inputs
from .seam import oracle as make_oracle


def build(
    root: int,
    inputs: Inputs,
    countries: list[str],
    *,
    exhaustive: bool = False,
    scalar_samples: int = 0,
    log: Callable[[str], None] | None = None,
) -> tuple[list[Row], Row]:
    if not set(countries) <= inputs.countries.keys():
        raise ValueError("A block touching an unfinished country must wait")
    started = time.monotonic()
    fine, coordinates = descendants(root, inputs.grid.cell_resolution)
    paths = {cc: inputs.paths[cc] for cc in countries}
    with Locator(
        paths, Path(inputs.land["path"]), inputs.policy, inputs.limits
    ) as locator:
        oracle = make_oracle(locator, paths, coordinates)
        prepared = time.monotonic()
        labels = label_block(oracle, fine, coordinates, inputs.grid.cell_resolution)
        labelled_at = time.monotonic()
        labelled = oracle.labelled_points
        stored, values = compact(fine, labels, grid=inputs.grid)
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
                    for level in range(
                        inputs.grid.block_resolution, inputs.grid.cell_resolution + 1
                    )
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
    stats = {
        "countries": countries,
        "enumerated": len(fine),
        "labelled": labelled,
        "eligible": int(np.count_nonzero(labels)),
        "resolutions": dict(resolutions),
        "checks": checks,
    }
    if log is not None:
        # Timings vary per run, so they are logged rather than recorded.
        log(
            f"cells block {h3.int_to_str(root)}: "
            f"{time.monotonic() - started:.3f}s, prepare {prepared - started:.3f}s, "
            f"label {labelled_at - prepared:.3f}s, "
            f"production {production_seconds:.3f}s"
        )
    return output_rows, stats
