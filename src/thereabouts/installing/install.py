"""Pinned, resumable installation with verification before atomic activation."""

import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..client_errors import InvalidInputError
from ..packs.errors import CorruptPackError
from ..packs.jsonio import (
    canonical,
    check_file,
    checksum,
    integer,
    parse,
    relative_file,
    sha256,
    string,
)
from ..packs.verify import verify
from ..store import data_directory, installation_path
from .errors import DownloadError, InstallationError
from .locking import installation_lock
from .transfer import transfer, validate_url


def _source(value: str | Path, offline: bool) -> str | Path:
    if isinstance(value, Path) or "://" not in value:
        return Path(value)
    if offline:
        raise DownloadError("Offline installation requires a local directory")
    return validate_url(value)


def _inventory(path: Path) -> tuple[str, list[dict[str, Any]]]:
    try:
        value = parse(path.read_bytes())
        if value["family"] != "reverse":
            raise ValueError("Only reverse packs can be installed")
        version = string(value["data_version"])
        records = value["files"]
        if not isinstance(records, list) or not records:
            raise ValueError("Missing payload inventory")
        seen = {"manifest.json"}
        for record in records:
            name = string(record["path"])
            relative_file(path.parent, name)
            if name in seen:
                raise ValueError("Duplicate or reserved path")
            seen.add(name)
            integer(record["size"])
            checksum(record["sha256"])
        return version, records
    except (ValueError, KeyError, TypeError) as exc:
        raise CorruptPackError(f"Invalid transfer inventory: {exc}") from exc


def _complete(root: Path, record: dict[str, Any]) -> bool:
    try:
        check_file(root, record, full=True)
    except (OSError, ValueError):
        return False
    return True


def _activate(root: Path, pack: Path, digest: str) -> None:
    pointer = relative_file(root, "packs/reverse/current.json")
    with tempfile.NamedTemporaryFile(
        dir=pointer.parent, prefix=".current-", delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(
                canonical(
                    {
                        "path": pack.relative_to(root.resolve()).as_posix(),
                        "manifest_sha256": digest,
                    }
                )
                + b"\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, pointer)
        finally:
            stream.close()
            temporary.unlink(missing_ok=True)


def install(
    source: str | Path,
    *,
    manifest_sha256: str,
    data_dir: str | Path | None = None,
    manifest_bytes: int | None = None,
    offline: bool = False,
    timeout: float = 30.0,
) -> Path:
    """Install an unpacked local directory or a pinned remote manifest URL.

    Remote manifests require their trusted byte count as well as SHA256. Each
    payload is bounded by the pinned inventory; no archive is extracted.
    Repeating after a failure reuses only whole artifacts whose hashes match.
    """
    try:
        checksum(manifest_sha256)
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        origin = _source(source, offline)
        if manifest_bytes is None:
            if isinstance(origin, str):
                raise ValueError("Remote installation requires manifest_bytes")
            manifest_bytes = relative_file(origin, "manifest.json").stat().st_size
        integer(manifest_bytes, 1)
    except (ValueError, TypeError) as exc:
        raise InvalidInputError(str(exc)) from exc
    except OSError as exc:
        raise InstallationError(f"Cannot read installation source: {exc}") from exc
    root = data_directory(data_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock = relative_file(root, "packs/reverse/install.lock")
        with installation_lock(lock):
            return _install(origin, root, manifest_sha256, manifest_bytes, timeout)
    except ValueError as exc:
        raise CorruptPackError(f"Unsafe installation path: {exc}") from exc
    except OSError as exc:
        raise InstallationError(f"Installation I/O failed: {exc}") from exc


def _install(
    source: str | Path, root: Path, digest: str, size: int, timeout: float
) -> Path:
    stage = relative_file(root, f"staging/{digest}")
    stage.mkdir(parents=True, exist_ok=True)
    manifest = relative_file(stage, "manifest.json")
    pinned = {"path": "manifest.json", "size": size, "sha256": digest}
    if not _complete(stage, pinned):
        if shutil.disk_usage(root).free < size:
            raise InstallationError("Insufficient disk space for pinned manifest")
        transfer(
            source, "manifest.json", manifest, size=size, digest=digest, timeout=timeout
        )
    version, records = _inventory(manifest)
    destination = installation_path(root, version, digest)
    if destination.exists():
        if verify(destination)["manifest_sha256"] != digest:
            raise CorruptPackError("Existing installation has a different manifest")
        shutil.rmtree(stage)
        _activate(root, destination, digest)
        return destination
    pending = [record for record in records if not _complete(stage, record)]
    if shutil.disk_usage(root).free < sum(record["size"] for record in pending):
        raise InstallationError("Insufficient disk space for pinned payloads")
    for record in pending:
        target = relative_file(stage, record["path"])
        transfer(
            source,
            record["path"],
            target,
            size=record["size"],
            digest=record["sha256"],
            timeout=timeout,
        )
    if verify(stage)["manifest_sha256"] != digest or sha256(manifest) != digest:
        raise CorruptPackError("Staged manifest changed during verification")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage.rename(destination)
    _activate(root, destination, digest)
    return destination
