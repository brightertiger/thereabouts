"""External merge sorting retains every duplicate across runs and merge passes."""

import hashlib
import random
from collections import Counter
from pathlib import Path

import pytest

from pipeline.config.content import DigestLimits
from pipeline.content import sorting as digest_sort


def test_multiple_merge_passes_preserve_sorted_multiplicities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = [hashlib.sha256(str(i % 43).encode()).digest() for i in range(500)]
    random.Random(14).shuffle(values)
    sorter = digest_sort.RowHashes(
        tmp_path / "runs", DigestLimits(chunk_rows=7, merge_fan_in=3)
    )
    sorter.add(values)
    assert list(sorter.counts()) == sorted(Counter(values).items())


def test_empty_and_invalid_hashes(tmp_path: Path) -> None:
    sorter = digest_sort.RowHashes(
        tmp_path / "runs", DigestLimits(chunk_rows=7, merge_fan_in=3)
    )
    assert list(sorter.counts()) == []
    with pytest.raises(ValueError, match="SHA256"):
        sorter.add([b"short"])
