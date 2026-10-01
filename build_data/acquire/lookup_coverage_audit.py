"""Measure global H3 coverage without expanding compacted timezone interiors."""

from pathlib import Path

import h3.api.basic_int as h3i
import numpy as np
import pyarrow.parquet as pq


def world_coverage(paths: list[Path]) -> dict[str, int]:
    """Map logical descendants to dense ranks; union their closed intervals.

    cell_to_child_pos handles the deleted pentagon digit, so this does not
    confuse unused H3 bit patterns with actual resolution-8 cells.
    """
    offsets: dict[int, int] = {}
    total = 0
    for root in sorted(h3i.get_res0_cells()):
        offsets[root] = total
        total += h3i.cell_to_children_size(root, 8)
    count = sum(pq.read_metadata(path).num_rows for path in paths)
    intervals = np.empty((count, 2), dtype=np.int64)
    index = 0
    expanded = 0
    for path in paths:
        with pq.ParquetFile(path) as parquet:
            for batch in parquet.iter_batches(columns=["h3_uint64"], batch_size=8192):
                for cell in batch.column(0).to_pylist():
                    size = h3i.cell_to_children_size(cell, 8)
                    first = h3i.cell_to_center_child(cell, 8)
                    start = offsets[
                        h3i.cell_to_parent(cell, 0)
                    ] + h3i.cell_to_child_pos(first, 0)
                    intervals[index] = start, start + size - 1
                    index += 1
                    expanded += size
    if not count:
        return dict(
            world_cells=total,
            covered_cells=0,
            missing_cells=total,
            duplicate_memberships=0,
        )
    intervals = intervals[np.argsort(intervals[:, 0])]
    previous_end = np.maximum.accumulate(intervals[:, 1])
    gaps = int(np.maximum(0, intervals[1:, 0] - previous_end[:-1] - 1).sum())
    covered = int(previous_end[-1] - intervals[0, 0] + 1) - gaps
    return dict(
        world_cells=total,
        covered_cells=covered,
        missing_cells=total - covered,
        duplicate_memberships=expanded - covered,
    )
