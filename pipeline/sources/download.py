"""Fetch frozen source bytes and verify their mirror before completing a unit."""

import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from http.client import HTTPException
from pathlib import Path
from typing import Any, BinaryIO, cast

from pipeline.pins.models import PinFile
from pipeline.runtime.jsonio import atomic_output, sha256_file, write_json
from pipeline.storage.objects import backend, copy_stream, fetch, mirror

from .contract import SourceContext
from .shared.manifest import inventory_path


def mirror_url(base: str, pin: PinFile) -> str:
    return base.rstrip("/") + "/sha256/" + pin.sha256


@contextmanager
def upstream(pin: PinFile, timeout: float) -> Iterator[BinaryIO]:
    if pin.url.startswith(("http://", "https://")):
        headers = {"Accept-Encoding": "identity", "User-Agent": "Thereabouts/pipeline"}
        if pin.etag and not pin.etag.startswith("W/"):
            headers["If-Match"] = pin.etag
        elif pin.last_modified:
            headers["If-Unmodified-Since"] = pin.last_modified
        request = urllib.request.Request(pin.url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            yield cast(BinaryIO, response)
    else:
        fs, name = backend(pin.url)
        with fs.open(name, "rb") as stream:
            yield stream


def acquire(ctx: SourceContext, pin: PinFile, base: str) -> Path:
    target = ctx.input(pin.name)
    limits = ctx.settings.limits
    if target.exists():
        if target.stat().st_size != pin.size or sha256_file(target) != pin.sha256:
            raise ValueError(f"Local pinned input is corrupt: {ctx.relative(target)}")
    else:
        mirrors = [mirror_url(base, pin)]
        if retained := ctx.pin.metadata.get("mirror_base"):
            mirrors.append(str(retained).rstrip("/") + "/" + pin.name)
        restored = False
        for remote in mirrors:
            fs, name = backend(remote)
            if fs.exists(name):
                fetch(remote, target, pin.size, pin.sha256, limits.read_bytes)
                restored = True
                break
        if not restored:
            delay = limits.backoff_seconds
            for attempt in range(limits.retries + 1):
                try:
                    with (
                        atomic_output(target) as temporary,
                        upstream(pin, limits.timeout_seconds) as stream,
                        temporary.open("wb") as output,
                    ):
                        copy_stream(
                            stream, output, pin.size, pin.sha256, limits.read_bytes
                        )
                    break
                except (OSError, HTTPException, urllib.error.URLError):
                    if attempt == limits.retries:
                        raise
                    time.sleep(delay)
                    delay = min(limits.timeout_seconds, delay * 2)
    # Existing local files must also be mirrored; a failed mirror leaves no unit
    # completion, while the verified local file can be reused on the next attempt.
    mirror(target, mirror_url(base, pin), pin.size, pin.sha256, limits.read_bytes)
    return target


def inventory(ctx: SourceContext) -> dict[str, Any]:
    return {
        "source": ctx.settings.name,
        "source_release": ctx.pin.release,
        "pinned_at": ctx.pin.pinned_at,
        "pin_metadata": ctx.pin.metadata,
        "files": {
            pin.name: {**asdict(pin), "path": ctx.relative(ctx.input(pin.name))}
            for pin in ctx.pin.files
        },
    }


def download(ctx: SourceContext) -> list[Path]:
    if ctx.runtime.readonly:
        raise ValueError("Cannot download with a read-only context")
    base = ctx.runtime.storage.get("gcs_raw")
    if not base:
        raise ValueError("Configure storage.gcs_raw before downloading source data")
    total = sum(pin.size for pin in ctx.pin.files)
    if total > ctx.settings.limits.download_bytes:
        raise ValueError(
            f"Pinned source exceeds {ctx.settings.name}.limits.download_bytes"
        )
    paths = [acquire(ctx, pin, base) for pin in ctx.pin.files]
    manifest = inventory_path(ctx)
    write_json(manifest, inventory(ctx))
    return [*paths, manifest]
