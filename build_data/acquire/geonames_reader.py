"""Geonames reader."""

from __future__ import annotations

import time
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from . import Ledger, Workspace, atomic_output, fingerprint, sha256_file
from .geonames_download import FILES, SOURCE
from .geonames_rows import BUILDER_VERSION, Row
from .geonames_settings import READ_BYTES
from .io import write_json
from .runtime import source_budget


def _extract_member(
    workspace: Workspace, archive: Path, member: str, pin: Mapping[str, object]
) -> Path:
    ledger = Ledger(workspace.ledger_path)
    key = f"extract/{archive.name}/{member}"
    digest = fingerprint(
        {"archive": pin["sha256"], "member": member, "builder": BUILDER_VERSION}
    )
    destination = workspace.work / SOURCE / "extracted" / digest / member
    outputs = ledger.completed_outputs("geonames.extract", key, digest)
    if outputs is not None:
        return outputs[0]
    if Path(member).name != member:
        raise ValueError(f"Unexpected nested or unsafe archive member: {member}")
    started = time.monotonic()
    with zipfile.ZipFile(archive) as zipped:
        info = zipped.getinfo(member)
        source_budget(workspace, SOURCE, info.file_size)
        with (
            atomic_output(
                destination, lambda path: _check_size(path, info.file_size)
            ) as temp,
            zipped.open(info) as source,
            temp.open("wb") as target,
        ):
            count, last = 0, b""
            while block := source.read(READ_BYTES):
                target.write(block)
                count += block.count(b"\n")
                last = block[-1:]
            count += bool(last and last != b"\n")
    report = destination.with_name(destination.name + ".json")
    write_json(
        report,
        {
            "member": member,
            "bytes": info.file_size,
            "crc32": info.CRC,
            "crc_valid": True,
            "lines": count,
            "sha256": sha256_file(destination),
            "seconds": round(time.monotonic() - started, 3),
        },
    )
    ledger.complete("geonames.extract", key, digest, [destination, report])
    print(f"Extracted {member}: {count:,} lines", flush=True)
    return destination


def _check_size(path: Path, expected: int) -> None:
    if path.stat().st_size != expected:
        raise ValueError(f"Extracted size mismatch: {path}")


def extract(workspace: Workspace, inventory: Row) -> dict[str, Path]:
    pins = cast(dict[str, Row], inventory["files"])
    result: dict[str, Path] = {}
    for name in FILES:
        pin = pins[name]
        path = Path(str(pin["path"]))
        if sha256_file(path) != pin["sha256"]:
            raise ValueError(f"Raw input checksum mismatch: {path}")
        if name.endswith(".zip"):
            with zipfile.ZipFile(path) as zipped:
                members = [
                    item.filename for item in zipped.infolist() if not item.is_dir()
                ]
            for member in members:
                result[member] = _extract_member(workspace, path, member, pin)
        else:
            result[name] = path
    return result
