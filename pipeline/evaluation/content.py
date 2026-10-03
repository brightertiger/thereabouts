"""Digest logical golden tables, independent of row order and Parquet metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from pipeline.engines.artifacts import read_json
from pipeline.engines.reconcile.common import Row
from pipeline.runtime.jsonio import digest as fingerprint
from pipeline.runtime.jsonio import write_json
from pipeline.runtime.paths import located

from .sorting import RowHashes


def canonical(value: Any) -> Any:
    """Encode values losslessly; NaNs share one representation, null stays distinct."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return ["float", value.hex()]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, Decimal):
        return ["decimal", str(value)]
    if isinstance(value, (datetime, date, time)):
        return [type(value).__name__, value.isoformat()]
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    raise TypeError(f"Unsupported golden value type: {type(value).__name__}")


def logical_type(kind: pa.DataType) -> Any:
    """Ignore Arrow metadata and dictionary encoding, retain logical column types."""
    if pa.types.is_dictionary(kind):
        return logical_type(kind.value_type)
    if pa.types.is_struct(kind):
        return {"struct": columns(pa.schema(list(kind)))}
    if pa.types.is_list(kind) or pa.types.is_large_list(kind):
        return {"list": logical_type(kind.value_type)}
    if pa.types.is_fixed_size_list(kind):
        return {"list": logical_type(kind.value_type), "size": kind.list_size}
    if pa.types.is_map(kind):
        return {"map": [logical_type(kind.key_type), logical_type(kind.item_type)]}
    return str(kind)


def columns(schema: pa.Schema) -> list[Row]:
    if len(set(schema.names)) != len(schema):
        raise ValueError("Duplicate column names in golden table")
    return [
        {"name": f.name, "type": logical_type(f.type)}
        for f in sorted(schema, key=lambda f: f.name)
    ]


def table_digest(records: list[Row], scratch: Path) -> Row:
    """Sort a multiset of SHA256 row digests using bounded sequential scratch."""
    schema: list[Row] | None = None
    count = 0
    with tempfile.TemporaryDirectory(prefix=scratch.stem, dir=scratch.parent) as work:
        sorter = RowHashes(Path(work) / "runs")
        for record in records:
            with pq.ParquetFile(record["path"]) as file:
                actual = columns(file.schema_arrow)
                if schema is not None and schema != actual:
                    raise ValueError("Inconsistent schemas within a logical table")
                schema = actual
                names = [f["name"] for f in schema]
                if file.metadata.num_rows != record["rows"]:
                    raise ValueError(f"Manifest row count differs: {record['path']}")
                for batch in file.iter_batches(batch_size=1024, columns=names):
                    hashes = []
                    for row in batch.to_pylist():
                        encoded = json.dumps(
                            [canonical(row[n]) for n in names],
                            sort_keys=True,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")
                        hashes.append(hashlib.sha256(encoded).digest())
                    sorter.add(hashes)
                    count += batch.num_rows
        digest = hashlib.sha256(b"thereabouts-golden-rows-v1\0")
        digest.update(fingerprint({"columns": schema}).encode("ascii"))
        for row_hash, occurrences in sorter.counts():
            digest.update(row_hash)
            digest.update(occurrences.to_bytes(8, "big"))
    return {"columns": schema, "rows": count, "sha256": digest.hexdigest()}


def digest_dataset(
    directory: Path, *, temp_dir: Path, manifest_path: Path | None = None
) -> Row:
    """Read listed partitions, preserving duplicates and empty tables."""
    saved = read_json(manifest_path or directory / "manifest.json")
    if not saved.get("completed") or not saved.get("tables"):
        raise ValueError("Content comparison requires a completed golden manifest")
    grouped: dict[str, list[Row]] = defaultdict(list)
    seen: set[Path] = set()
    for record in saved["tables"]:
        path = located(directory, record["path"])
        if path in seen:
            raise ValueError(f"Duplicate manifest partition: {path}")
        seen.add(path)
        grouped[record["kind"]].append({**record, "path": str(path)})
    tables = {}
    with tempfile.TemporaryDirectory(prefix="golden-digest-", dir=temp_dir) as work:
        for number, kind in enumerate(sorted(grouped)):
            scratch = Path(work) / f"{number}"
            tables[kind] = table_digest(grouped[kind], scratch)
            print(f"digested {kind}: {tables[kind]['rows']:,} rows", flush=True)
    result: Row = {"format": "thereabouts-golden-content-1", "tables": tables}
    return {**result, "sha256": fingerprint(result)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Manifest whose paths are relative to dataset root",
    )
    parser.add_argument("--compare", type=Path, help="Fail if a saved digest differs")
    parser.add_argument(
        "--temp-dir",
        type=Path,
        required=True,
        help="Scratch for bounded-memory sorting",
    )
    args = parser.parse_args()
    if (
        args.output.resolve()
        == (args.manifest or args.dataset / "manifest.json").resolve()
    ):
        parser.error("--output must not overwrite the dataset manifest")
    if args.compare and args.output.resolve() == args.compare.resolve():
        parser.error("--output must not overwrite --compare")
    value = digest_dataset(
        args.dataset, temp_dir=args.temp_dir, manifest_path=args.manifest
    )
    write_json(args.output, value)
    if args.compare and read_json(args.compare) != value:
        raise SystemExit("Golden table contents differ; inspect the per-table digests")
    print(value["sha256"])


if __name__ == "__main__":
    main()
