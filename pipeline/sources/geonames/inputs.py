"""Verified GeoNames archives are the authority for regenerable extracted caches."""

from pathlib import Path

from pipeline.pins.models import PinFile
from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.archives import extract

from .rows import Row


def evidence(ctx: SourceContext, pin: PinFile) -> Row:
    return {
        "url": pin.url,
        "sha256": pin.sha256,
        "retrieved_at": ctx.pin.pinned_at,
        "last_modified": pin.last_modified,
        "license": ctx.settings.licence.id,
        "license_url": ctx.settings.licence.url,
        "attribution": ctx.settings.licence.attribution,
        **pin.metadata,
        "kept_classes": ctx.settings.options["kept_classes"],
    }


def inputs(ctx: SourceContext) -> tuple[dict[str, Path], list[Path]]:
    paths: dict[str, Path] = {}
    caches: list[Path] = []
    for pin in ctx.pin.files:
        if pin.name.endswith(".zip"):
            extracted = extract(
                ctx,
                ctx.input(pin.name),
                ctx.work / ctx.inputs_hash / "extracted",
                lambda name: True,
            )
            for path in extracted:
                if path.name in paths:
                    raise ValueError(f"Duplicate GeoNames archive member {path.name}")
                paths[path.name] = path
            caches.extend(extracted)
        else:
            paths[str(pin.metadata.get("key", pin.name))] = ctx.input(pin.name)
    for name in ("allCountries.txt", "alternateNamesV2.txt"):
        if name not in paths:
            raise ValueError(f"Missing GeoNames input {name}")
    return paths, caches
