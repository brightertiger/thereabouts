"""Stable upstream identities of a reconcile country artifact's stored areas.

Area IDs are insertion sequence numbers, so any rebuild renumbers them. Reviews
name a city boundary by the upstream records of its areas instead; those survive
a rebuild of the same evidence. Only gate code imports this module.
"""

import json
from collections.abc import Callable
from pathlib import Path

from pipeline.engines.store.codec import Row, unpack
from pipeline.engines.store.database import connect


def origin(evidence: Row) -> str:
    """One stored area part's upstream record, without its edit version."""
    provenance = evidence.get("provenance") or {}
    if isinstance(provenance, str):
        provenance = json.loads(provenance)
    sources = (provenance.get("upstream") or {}).get("sources") or []
    # Overture names the record behind each property; "" is the whole feature.
    whole = [s for s in sources if s.get("property") == "" and s.get("record_id")]
    if len(whole) == 1:
        name = f"{whole[0]['provider']}:{whole[0]['record_id'].partition('@')[0]}"
    elif evidence.get("source") and evidence.get("source_id"):
        name = f"{evidence['source']}:{evidence['source_id']}"
    else:
        raise ValueError("Source area evidence names no upstream record")
    part = provenance.get("geometry_part") or 0
    return f"{name}#{part}" if part else name


def boundary_origins(path: Path, references: list[str], cache_kib: int) -> list[str]:
    """Sorted unique origins; a non-numeric reference is already an identity."""
    result = {r for r in references if not r.isdigit()}
    areas = [int(r) for r in references if r.isdigit()]
    if not areas:
        return sorted(result)
    db = connect(path, readonly=True, cache_kib=cache_kib)
    try:
        for area in areas:
            row = db.execute(
                "SELECT evidence FROM areas WHERE id=?", (area,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Boundary names a missing source area {area}: {path}")
            result.add(origin(unpack(row[0])))
    finally:
        db.close()
    return sorted(result)


def resolver(
    source: Callable[[str], Path], cache_kib: int
) -> Callable[[Row], list[str]]:
    """Resolve a loss's references in its own country's reconcile database."""

    def resolve(loss: Row) -> list[str]:
        return boundary_origins(source(loss["country"]), loss["references"], cache_kib)

    return resolve
