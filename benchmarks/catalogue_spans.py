"""Measure physical catalogue ranges from the normative record and offset layout."""

import struct
from pathlib import Path
from typing import Any

import numpy as np


def spans(pack: Path) -> dict[str, Any]:
    """Report the actual hot text span per row, not a guessed shard-size ratio."""
    text_lengths: list[int] = []
    offset_lengths = []
    full_lengths: list[int] = []
    shards = 0
    for path in sorted(pack.glob("catalogue-*.bin")):
        data = path.read_bytes()
        records, length = struct.unpack_from("<QQ", data, 40)
        offsets = struct.unpack_from("<Q", data, 72)[0]
        for row in range(records, records + length, 80):
            fields = list(struct.unpack_from("<12I", data, row))
            fields.append(struct.unpack_from("<I", data, row + 76)[0])
            for hot, destination in [(True, text_lengths), (False, full_lengths)]:
                refs = [v for i, v in enumerate(fields) if v and (not hot or i != 11)]
                first, last = min(refs), max(refs)
                start = struct.unpack_from("<Q", data, offsets + first * 8)[0]
                stop = struct.unpack_from("<Q", data, offsets + (last + 1) * 8)[0]
                destination.append(stop - start)
                if hot:
                    offset_lengths.append((last - first + 2) * 8)
        shards += 1
    return {
        "catalogue_shards": shards,
        "places": len(text_lengths),
        "hot_text_median_bytes": float(np.median(text_lengths)),
        "hot_text_p99_bytes": float(np.percentile(text_lengths, 99)),
        "hot_text_max_bytes": max(text_lengths),
        "hot_offsets_max_bytes": max(offset_lengths),
        "full_text_max_bytes": max(full_lengths),
    }
