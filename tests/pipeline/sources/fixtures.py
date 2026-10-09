"""Small frozen source archives and contexts; every upstream is in memory."""

import hashlib
import io
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import shapely

from pipeline.config import load
from pipeline.pins.models import PinFile, SourcePin
from pipeline.runtime.ledger import Ledger
from pipeline.runtime.resources import ResourceGuard
from pipeline.sources.contract import SourceContext
from pipeline.stages.contract import make_unit
from pipeline.stages.sources import SourceStage
from pipeline.storage.objects import backend

from ..helpers import context


def archive(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as stream:
        for name, payload in members.items():
            stream.writestr(name, payload)
    return output.getvalue()


def parquet(rows: list[dict[str, Any]]) -> bytes:
    output = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(rows), output, row_group_size=1)
    return output.getvalue()


def feature(identifier: int, feature_class: str = "P", code: str = "PPL") -> bytes:
    return (
        "\t".join(
            [
                str(identifier),
                "Cafe\u0301",
                "Cafe",
                "Coffee",
                "1.5",
                "2.5",
                feature_class,
                code,
                "US",
                "",
                "01",
                "002",
                "003",
                "004",
                "0",
                "42",
                "45",
                "Etc/UTC",
                "2026-10-01",
            ]
        )
        + "\n"
    ).encode()


def alternate(
    identifier: int, entity: int, name: str = "Coffee", historic: str = ""
) -> bytes:
    return (
        "\t".join(
            [str(identifier), str(entity), "en", name, "1", "", "", historic, "", ""]
        )
        + "\n"
    ).encode()


def division() -> dict[str, Any]:
    return {
        "id": "point",
        "geometry": shapely.Point(2.5, 1.5).wkb,
        "names": {"primary": "Cafe\u0301", "common": {"en": "Coffee"}},
        "subtype": "locality",
        "class": "city",
        "country": "US",
        "region": "US-NY",
        "admin_level": 3,
        "parent_division_id": "parent",
        "population": 0,
    }


def source_context(
    root: Path,
    ledger: Ledger,
    name: str,
    payloads: dict[str, tuple[bytes, dict[str, Any]]],
) -> tuple[SourceContext, list[SourceStage]]:
    config = load()
    settings = config.sources[name]
    # The source under test runs whether or not the committed config enables it.
    settings.enabled = True
    settings.limits = replace(
        settings.limits,
        download_bytes=sum(len(p) for p, _ in payloads.values()),
        retries=0,
    )
    config.sources = {name: settings}
    ctx = context(root, ledger)
    ctx.config = config
    ctx.storage = {"gcs_raw": "memory://mirrors/" + root.name}
    ctx.guard = ResourceGuard(
        root,
        config.resources,
        free=lambda _: 10_000_000_000,
        used=lambda _: 0,
        rss=lambda: 0,
    )
    files = []
    for key, (payload, metadata) in payloads.items():
        url = f"memory://upstreams/{root.name}/{name}/{key}"
        fs, remote = backend(url)
        with fs.open(remote, "wb") as stream:
            stream.write(payload)
        pin = PinFile(
            key,
            url,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            metadata={"key": key, "retrieved_at": "2026-10-03", **metadata},
        )
        files.append(pin)
    source_pin = SourcePin("synthetic", "2026-10-03", files=files)
    stages = [SourceStage(setting, {name: source_pin}) for setting in config.stages[:2]]
    unit = stages[1].units(ctx)[0]
    return SourceContext(
        ctx, settings, source_pin, make_unit(ctx, unit.recipe, unit.identity)
    ), stages


def rows(source: SourceContext, kind: str) -> list[dict[str, Any]]:
    result = []
    for path in sorted((source.normalized / kind).rglob("*.parquet")):
        result.extend(pq.read_table(path).to_pylist())
    return result
