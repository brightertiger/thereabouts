"""Owner-approved missing intermediates; present bytes must still verify."""

from collections import Counter
from collections.abc import Iterable

from .candidates import Candidate

RECONCILE_PREFIXES = ("reconciled/", "work/reconcile/")
NORMALIZE_PREFIXES = {
    "geonames": "work/geonames/",
    "overture": "work/overture/",
}


def absent_prefix(candidate: Candidate, path: str) -> str | None:
    if candidate.stage == "reconcile":
        return next((p for p in RECONCILE_PREFIXES if path.startswith(p)), None)
    if candidate.stage == "normalize":
        prefix = NORMALIZE_PREFIXES.get(candidate.unit_id)
        return prefix if prefix and path.startswith(prefix) else None
    if candidate.stage == "download" and candidate.custody:
        prefix = f"raw/{candidate.unit_id}/"
        return prefix if path.startswith(prefix) else None
    return None


def absent_counts(candidates: Iterable[Candidate]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for candidate in candidates:
        for path in candidate.absent:
            prefix = absent_prefix(candidate, path)
            if prefix is None:
                raise ValueError(f"Absence has no approved prefix: {path}")
            counts[prefix] += 1
    return dict(counts)
