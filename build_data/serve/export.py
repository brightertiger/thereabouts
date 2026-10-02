"""Input-keyed, resumable export with verification before atomic publication."""

import fcntl
import shutil
from functools import partial
from pathlib import Path

from build_data.acquire.io import sync_directory
from build_data.serve_codes.encoding import (
    shards as code_shards,
)
from build_data.serve_codes.encoding import (
    verify_source as verify_codes,
)
from build_data.serve_codes.index import CodeIndex
from build_data.serve_codes.source import NORMALIZATION
from thereabouts.packs.address import address
from thereabouts.packs.jsonio import digest
from thereabouts.packs.layout import (
    DEFAULT_SHARD_BYTES,
    DIRECTORY,
    LABEL,
    MAX_BLOCK_ROWS,
    PLACE,
    REAL_BLOCK_COUNT,
)
from thereabouts.packs.verify import verify

from .catalogue import CatalogueIndex
from .cells import write_cells
from .checkpoints import unit
from .encoding import CatalogueBuffer
from .equivalence import verify_source
from .metadata import identity, manifest, write_manifest
from .release import notices, release_metadata
from .snapshot import Row, Snapshot, read_snapshot


def catalogue_shards(
    index: CatalogueIndex, work: Path, pack: Path, fingerprint: str, shard_bytes: int
) -> list[Row]:
    result: list[Row] = []
    buffer = CatalogueBuffer()
    first = 1

    def flush() -> None:
        name = f"catalogue-{len(result):05d}.bin"
        fields = {
            "kind": "catalogue",
            "first_id": first,
            "count": len(buffer.records) // PLACE.size,
        }
        result.append(unit(work, pack, name, fingerprint, fields, buffer.write))

    for ref, value in index.records():
        # This upper bound counts all strings, even ones already interned. A
        # single indivisible place may exceed the transport target.
        added = PLACE.size + sum(
            len(v.encode("utf-8")) + 8 for v in value.values() if isinstance(v, str)
        )
        if buffer.records and buffer.size + added > shard_bytes:
            flush()
            buffer, first = CatalogueBuffer(), ref
        buffer.add(value)
    if buffer.records:
        flush()
    return result


def cell_shards(
    snapshot: Snapshot,
    index: CatalogueIndex,
    work: Path,
    pack: Path,
    fingerprint: str,
    shard_bytes: int,
) -> list[Row]:
    tables = sorted(
        snapshot.tables("cells"), key=lambda r: address(int(r["block"], 16), 3)[0]
    )
    # Flat labels bound either encoding; a real r3 block has at most 7**5 rows.
    per_block = MAX_BLOCK_ROWS * (2 + LABEL.size) + DIRECTORY.size
    group_size = max(1, shard_bytes // per_block)
    result: list[Row] = []
    for start in range(0, len(tables), group_size):
        group = tables[start : start + group_size]
        fields = {
            "kind": "cells",
            "first_block": address(int(group[0]["block"], 16), 3)[0],
            "last_block": address(int(group[-1]["block"], 16), 3)[0],
        }
        result.append(
            unit(
                work,
                pack,
                f"cells-{len(result):05d}.bin",
                fingerprint,
                fields,
                partial(write_cells, snapshot, group, index),
            )
        )
    return result


def export(
    snapshot_path: Path,
    metadata_path: Path,
    output: Path,
    *,
    shard_bytes: int = DEFAULT_SHARD_BYTES,
    family: str = "reverse",
) -> Path:
    if type(shard_bytes) is not int or shard_bytes < PLACE.size:
        raise ValueError("Shard target must fit a place record")
    if family not in ("reverse", "postal", "airports"):
        raise ValueError("Unknown serving family")
    output = output.resolve()
    snapshot = read_snapshot(snapshot_path)
    release = release_metadata(metadata_path)
    export_identity = identity(snapshot, release, shard_bytes)
    export_identity["family"] = family
    fingerprint = digest(export_identity)
    output.parent.mkdir(parents=True, exist_ok=True)
    with (output.parent / ".serve.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if output.exists():
            value = verify(output)
            if value["export_fingerprint"] != fingerprint:
                raise FileExistsError(
                    "Output belongs to different inputs; "
                    "choose a new immutable directory"
                )
            return output
        work = output.parent / (".serve-" + fingerprint)
        pack = work / "pack"
        pack.mkdir(parents=True, exist_ok=True)
        index = CatalogueIndex(work / "catalogue.sqlite")
        try:
            codes = None
            if family == "reverse":
                index.load(snapshot)
            else:
                codes = CodeIndex(index, snapshot, family)
                codes.load(release)
            files = catalogue_shards(index, work, pack, fingerprint, shard_bytes)
            files += (
                cell_shards(snapshot, index, work, pack, fingerprint, shard_bytes)
                if codes is None
                else code_shards(codes, work, pack, fingerprint, shard_bytes)
            )
            files += notices(snapshot, release, metadata_path, pack)
            coverage = (
                "world"
                if len(snapshot.tables("cells")) == REAL_BLOCK_COUNT
                else "blocks"
            )
            value = manifest(
                snapshot, release, export_identity, files, index.count, coverage
            )
            if codes is not None:
                value.update(
                    family=family,
                    coverage="keys",
                    key_normalization=NORMALIZATION[family],
                    candidate_policy="source-observations-1",
                    source_rows=codes.source_rows,
                    unindexed_rows=codes.unindexed_rows,
                )
            write_manifest(pack / "manifest.json", value)
            verify(pack)
            if codes is None:
                verify_source(snapshot, pack, files, index)
            else:
                verify_codes(codes, pack, files)
            snapshot.recheck()
            if {
                **identity(snapshot, release_metadata(metadata_path), shard_bytes),
                "family": family,
            } != export_identity:
                raise ValueError(
                    "Exporter code or release metadata changed during export"
                )
            pack.rename(output)
            sync_directory(output.parent)
        finally:
            index.close()
        shutil.rmtree(work)
    return output
