"""Read the exact pinned layer inventory, including source-specific licences."""

from pathlib import Path

from pipeline.runtime.jsonio import digest, write_json
from pipeline.sources.contract import SourceContext
from pipeline.sources.shared.archives import extract
from pipeline.sources.shared.manifest import finish

from .convert import _convert


def normalize(ctx: SourceContext) -> list[Path]:
    outputs: list[Path] = []
    auxiliary: list[Path] = []
    for item in ctx.pin.files:
        ctx.guard.admit()
        key = digest(item.name)
        directory = ctx.work / ctx.inputs_hash / key
        paths = extract(
            ctx,
            ctx.input(item.name),
            directory,
            lambda name: (
                Path(name).suffix in (".shp", ".shx", ".dbf", ".prj")
                and "_simplified" not in name
            ),
        )
        shps = [path for path in paths if path.suffix == ".shp"]
        if len(shps) != 1:
            raise ValueError("Expected one unsimplified geoBoundaries shapefile")
        shp = shps[0]
        projection = shp.with_suffix(".prj").read_text(encoding="utf-8")
        if (
            "GEOGCS" not in projection
            or "WGS_1984" not in projection
            or "PROJCS" in projection
        ):
            raise ValueError(f"Unexpected boundary CRS: {projection}")
        pin = {
            "url": item.url,
            "archive_sha256": item.sha256,
            "retrieved_at": ctx.pin.pinned_at,
            **item.metadata,
        }
        country = (
            ctx.pin.metadata["country_reference"]
            .get(pin["metadata"]["boundaryISO"], {})
            .get("alpha2")
        )
        partitions, report = _convert(ctx, pin, country, ctx.input(item.name), shp)
        audit = ctx.normalized / "audits" / ctx.inputs_hash / f"{key}.json"
        write_json(ctx.ensure(audit), report)
        outputs.extend(partitions)
        auxiliary.append(audit)
        # These are this run's extracted copies, regenerated from the pinned ZIP.
        for path in paths:
            path.unlink()
    return finish(ctx, outputs, auxiliary)
