"""Fetch frozen source bytes into content-addressed objects and mirror them."""

from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any

from pipeline.errors import ConfigError
from pipeline.pins.evidence import verify_publisher
from pipeline.pins.models import PinFile
from pipeline.runtime.jsonio import sha256_file, write_json
from pipeline.storage.objects import address, backend, mirror
from pipeline.storage.retry import Patience, retrying
from pipeline.storage.transfer import fetch

from .contract import SourceContext
from .shared.manifest import inventory_path


def mirror_url(base: str, pin: PinFile) -> str:
    return base.rstrip("/") + "/" + address(pin.sha256)


def conditions(pin: PinFile) -> dict[str, str]:
    """Ask upstream for the pinned representation only."""
    if pin.etag and not pin.etag.startswith("W/"):
        return {"If-Match": pin.etag}
    if pin.last_modified:
        return {"If-Unmodified-Since": pin.last_modified}
    return {}


def exists(url: str) -> bool:
    fs, name = backend(url)
    return fs.exists(name)


def intact(path: Path, pin: PinFile) -> bool:
    return path.stat().st_size == pin.size and sha256_file(path) == pin.sha256


def acquire(ctx: SourceContext, pin: PinFile, base: str) -> Path:
    target = ctx.input(pin.name)
    limits = ctx.settings.limits
    patience = Patience.of(limits)
    if target.exists() and not intact(target, pin):
        # The name is the checksum, so a mismatch is damage, never a new version.
        target.unlink()
    if not target.exists():
        remote = mirror_url(base, pin)
        mirrored = retrying(patience, partial(exists, remote))
        fetch(
            remote if mirrored else pin.url,
            target,
            size=pin.size,
            sha256=pin.sha256,
            headers={} if mirrored else conditions(pin),
            limits=limits,
        )
    verify_publisher(target, pin.metadata, limits.read_bytes, pin.name)
    # Existing local files must also be mirrored; a failed mirror leaves no unit
    # completion, while the verified local object is reused on the next attempt.
    retrying(
        patience,
        lambda: mirror(
            target, mirror_url(base, pin), pin.size, pin.sha256, limits.read_bytes
        ),
    )
    return target


def inventory(ctx: SourceContext) -> dict[str, Any]:
    """Map each logical name to its pinned record and content-addressed object."""
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
    # A SourceContext exists only for a writable run (stages.sources.adapter_context).
    base = ctx.storage.get("gcs_raw")
    if not base:
        raise ConfigError("Configure storage.gcs_raw before downloading source data")
    total = sum(pin.size for pin in ctx.pin.files)
    if total > ctx.settings.limits.download_bytes:
        raise ValueError(
            f"Pinned source exceeds {ctx.settings.name}.limits.download_bytes"
        )
    # Names that pin identical bytes share one object.
    paths = list(dict.fromkeys(acquire(ctx, pin, base) for pin in ctx.pin.files))
    manifest = inventory_path(ctx)
    write_json(manifest, inventory(ctx))
    return [*paths, manifest]
