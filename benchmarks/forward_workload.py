"""Seeded scalar timings and grouped columnar timings through the public Python API."""

import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from benchmarks.forward_queries import Query
from thereabouts import Geocoder

SEED = 271828


def run(pack: Path, verb: str, queries: list[Query], count: int) -> dict[str, Any]:
    """Visit every key once, then sample uniformly; batch groups preserve options."""
    rng = random.Random(SEED)
    values = queries.copy()
    rng.shuffle(values)
    values += rng.choices(queries, k=max(0, count - len(values)))
    durations, rates = [], []
    statuses: Counter[str] = Counter()
    groups: dict[tuple[tuple[str, str], ...], list[str]] = defaultdict(list)
    for query in values:
        groups[query.options].append(query.value)
    with Geocoder(pack) as geo:
        scalar, batch = getattr(geo, verb), getattr(geo, verb + "_columns")
        for query in values:
            kwargs = query.kwargs()
            start = time.perf_counter_ns()
            result = scalar(query.value, **kwargs)
            durations.append(time.perf_counter_ns() - start)
            statuses[result.status] += 1
        for _ in range(3):
            start_batch = time.perf_counter()
            for options, group in groups.items():
                result = batch(group, **dict(options))
                assert len(result["status"]) == len(group)
            rates.append(len(values) / (time.perf_counter() - start_batch))
    return {
        "queries": len(values),
        "distinct_queries": len(queries),
        "seed": SEED,
        "status_counts": dict(statuses),
        "scalar_median_us": statistics.median(durations) / 1000,
        "scalar_p99_us": float(np.percentile(durations, 99)) / 1000,
        "batch_points_per_second": statistics.median(rates),
    }
