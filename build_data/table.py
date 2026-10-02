"""Stream compact subtrees into local-key, local-dictionary mmap arrays."""

import json
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import BinaryIO

import numpy as np
from numpy.typing import NDArray

from thereabouts.format import (
    BITMAP_BYTES_PER_WORD,
    BITMAP_FLAG,
    BITMAP_WORD_BITS,
    BITMAP_WORD_DTYPE,
    BLOCK_COUNT,
    BLOCK_RESOLUTION,
    BYTE_BITS,
    CITY_CUTOFF_KM,
    DIRECTORY_DTYPE,
    KEY_DTYPE,
    LABEL_DTYPE,
    MAX_DICTIONARY_LABELS,
    VALUE_DTYPES,
    bitmap_word_count,
)
from thereabouts.hierarchy import addresses
from thereabouts.manifest import SCHEMA

from .hierarchy import blocks, compact, descendants, label_block
from .reference.oracle import Labels, Reference
from .settlements import settlement_policy
from .sources import sha256
from .verify import verify


def encode_keys(
    keys: NDArray[np.uint16], resolution: int
) -> tuple[NDArray[np.uint16], int]:
    """Choose the smaller of a sorted uint16 list and a ranked bitmap."""
    key_data = keys.astype(KEY_DTYPE)
    word_count = bitmap_word_count(resolution - BLOCK_RESOLUTION)
    encoding_flag = 0
    if len(keys) * KEY_DTYPE.itemsize > word_count * BITMAP_BYTES_PER_WORD:
        words = np.zeros(word_count, dtype=BITMAP_WORD_DTYPE)
        np.bitwise_or.at(
            words,
            keys // BITMAP_WORD_BITS,
            np.uint64(1) << (keys.astype(np.uint64) % BITMAP_WORD_BITS),
        )
        ranks = np.r_[
            0, np.cumsum(np.bitwise_count(words)[:-1], dtype=np.uint16)
        ].astype(KEY_DTYPE)
        key_data = np.concatenate((words.view(KEY_DTYPE), ranks))
        encoding_flag = BITMAP_FLAG
    return key_data, encoding_flag


class Writer:
    def __init__(self, path: Path, resolution: int = 8) -> None:
        self.resolution = resolution
        self.path = path
        self.directory = np.zeros(BLOCK_COUNT, dtype=DIRECTORY_DTYPE)
        self.streams: dict[str, BinaryIO] = {
            part: (path / f"combined-{part}.bin").open("wb")
            for part in ("keys", "values", "dictionary")
        }
        self.rows = 0

    def write(self, block: int, keys: NDArray[np.uint16], labels: Labels) -> None:
        dictionary, inverse = np.unique(labels, return_inverse=True)
        width = 1 if len(dictionary) <= 1 << BYTE_BITS else 2
        if len(dictionary) > MAX_DICTIONARY_LABELS:
            raise ValueError("block dictionary exceeds uint16 capacity")
        keyfile, valuefile, dictfile = (
            self.streams[p] for p in ("keys", "values", "dictionary")
        )
        key_data, encoding_flag = encode_keys(keys, self.resolution)
        self.directory[block] = (
            keyfile.tell() // KEY_DTYPE.itemsize,
            valuefile.tell(),
            dictfile.tell() // LABEL_DTYPE.itemsize,
            len(keys),
            len(dictionary),
            width | encoding_flag,
        )
        key_data.tofile(keyfile)
        inverse.astype(VALUE_DTYPES[width]).tofile(valuefile)
        dictionary.astype(LABEL_DTYPE).tofile(dictfile)
        self.rows += len(keys)

    def close(self) -> None:
        for stream in self.streams.values():
            stream.close()
        np.save(
            self.path / "combined-directory.npy", self.directory, allow_pickle=False
        )


def write_metadata(
    reference: Reference, reference_path: Path, output: Path, resolution: int
) -> None:
    """Serialize the shared name pool, provenance and file checksums."""
    catalog_data = reference.catalog()
    city_strings = [(name or "").encode("utf-8") for name in catalog_data.pop("cities")]
    np.cumsum([0, *(len(s) for s in city_strings)], dtype="<u4").tofile(
        output / "city-offsets.bin"
    )
    (output / "city-text.bin").write_bytes(b"".join(city_strings))
    catalog = json.dumps(catalog_data, ensure_ascii=False, separators=(",", ":"))
    (output / "catalog.json").write_text(catalog, encoding="utf-8")
    shutil.copyfile(reference_path / "DATA_LICENSES.txt", output / "DATA_LICENSES.txt")
    source_manifest = reference.pack.manifest
    manifest = {
        "schema_version": SCHEMA,
        "resolution": resolution,
        "layout": "combined",
        "city_cutoff_km": CITY_CUTOFF_KM,
        "settlement_policy": source_manifest["settlement_policy"],
        "snapshot_id": source_manifest["snapshot_id"] + f"-h3-r{resolution}",
        "ambiguity": "lexically smallest Natural Earth source ID in each layer",
        "coverage_bbox": source_manifest["coverage_bbox"],
        "eligibility": (
            "Natural Earth land or country coverage; admin1 alone is insufficient"
        ),
        "sources": source_manifest["sources"],
        "attribution": source_manifest["attribution"],
        "reference_manifest_sha256": sha256(reference_path / "manifest.json"),
        "files": {
            p.name: {"size": p.stat().st_size, "sha256": sha256(p)}
            for p in sorted(output.iterdir())
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def _build_table(
    reference_path: Path, output: Path, resolution: int = 8
) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    output.mkdir(parents=True)
    started = time.perf_counter()
    reference = Reference(reference_path)
    if reference.pack.manifest.get("settlement_policy") != settlement_policy():
        reference.close()
        raise ValueError(
            "Reference settlement policy is stale; rebuild the source pack"
        )
    writer = Writer(output, resolution)
    count = 0
    try:
        for number, root in enumerate(
            blocks(reference.pack.manifest["coverage_bbox"], resolution)
        ):
            cells, coordinates = descendants(root, resolution)
            count += len(cells)
            labels = label_block(reference, cells, coordinates, resolution)
            block = addresses(root, BLOCK_RESOLUTION)[0]
            writer.write(block, *compact(cells, labels, resolution))
            if (number + 1) % 1000 == 0:
                print(
                    json.dumps(
                        {
                            "blocks": number + 1,
                            "seconds": round(time.perf_counter() - started, 2),
                            "centres_labelled": reference.labelled_points,
                        }
                    ),
                    flush=True,
                )
        writer.close()
        write_metadata(reference, reference_path, output, resolution)
        stats: dict[str, object] = {
            "resolution": resolution,
            "build_seconds": time.perf_counter() - started,
            "labelling_peak_process_rss_bytes": resource.getrusage(
                resource.RUSAGE_SELF
            ).ru_maxrss
            * (1 if sys.platform == "darwin" else 1024),
            "centres_enumerated": count,
            "centres_labelled": reference.labelled_points,
            "table_bytes": sum(p.stat().st_size for p in output.glob("combined-*")),
            "rows": writer.rows,
            "catalog_bytes": (output / "catalog.json").stat().st_size,
        }
        print(json.dumps(stats), flush=True)
        return stats
    finally:
        for stream in writer.streams.values():
            stream.close()
        reference.close()


def build_table(
    reference_path: Path, output: Path, resolution: int = 8
) -> dict[str, object]:
    """Verify a temporary immutable pack before publishing its directory."""
    if resolution not in (6, 7, 8):
        raise ValueError("finest resolution must be 6, 7 or 8")
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(
        prefix=".h3-build-", dir=output.parent
    ) as temporary:
        pack = Path(temporary) / "pack"
        stats = _build_table(reference_path, pack, resolution)
        verify(pack)
        pack.rename(output)
    stats["build_seconds"] = time.perf_counter() - started
    return stats
