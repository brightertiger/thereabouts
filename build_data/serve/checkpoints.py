"""Verified per-shard checkpoints and portable artifact records."""

from collections.abc import Callable
from pathlib import Path

from build_data.acquire.io import write_json
from thereabouts.packs.jsonio import check_file, parse, sha256

from .snapshot import Row


def file_record(path: Path, root: Path, **fields: object) -> Row:
    return {
        "path": path.relative_to(root).as_posix(),
        "size": path.stat().st_size,
        "sha256": sha256(path),
        **fields,
    }


def unit(
    work: Path,
    pack: Path,
    name: str,
    fingerprint: str,
    fields: Row,
    write: Callable[[Path], None],
) -> Row:
    receipt = work / (name + ".json")
    if receipt.exists():
        try:
            previous = parse(receipt.read_bytes())
            record = previous["file"]
            if not isinstance(record, dict) or record.get("path") != name:
                raise ValueError("Invalid shard receipt")
            if previous["fingerprint"] == fingerprint and all(
                record[k] == v for k, v in fields.items()
            ):
                check_file(pack, record, full=True)
                return record
        except (OSError, KeyError, TypeError, ValueError):
            pass  # Only this stage's incomplete/corrupt shard is rebuilt.
    path = pack / name
    write(path)
    record = file_record(path, pack, **fields)
    write_json(receipt, {"fingerprint": fingerprint, "file": record})
    return record
