"""Timezone memberships and code/telephone joins independent of cell building."""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pyarrow as pa

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import file_record
from build_data.acquire.io import fingerprint
from build_data.acquire.ledger import read_units
from build_data.acquire.manifests import load_manifest
from build_data.reconcile.common import Row

from .code_links import CodeIndex
from .code_links import linked_rows as linked_rows
from .inputs import Inputs
from .phone import PhoneCountries
from .schemas import strings
from .storage import budget, parquet


def export(workspace: Workspace, inputs: Inputs) -> list[Row]:
    import pyarrow.parquet as pq

    ledger = Ledger(workspace.ledger_path)
    previous = {
        r["unit_id"]: r for r in read_units(workspace.ledger_path, "golden.static")
    }
    index = CodeIndex(inputs)
    countries, codes = index.countries, index.codes
    phone_manifest = load_manifest(workspace, "phone")
    phone = PhoneCountries(
        [
            Path(p["path"])
            for p in phone_manifest["partitions"]
            if p["kind"] == "phone_metadata"
        ]
    )
    result = []
    for source in ("timezones", "codes", "phone"):
        manifest = load_manifest(workspace, source)
        for part in manifest["partitions"]:
            kind = part["kind"]
            if kind == "timezones":
                continue  # Cell memberships and IANA evidence are the golden tables.
            source_path = Path(part["path"])
            unit = f"{kind}/{source_path.stem}"
            digest = fingerprint(
                {
                    "part": part,
                    "static": 4,
                    "phone_metadata": phone_manifest if source == "phone" else None,
                    "countries": inputs.countries if source != "timezones" else {},
                }
            )
            if ledger.is_complete("golden.static", unit, digest):
                result.append(previous[unit]["metadata"]["table"])
                continue
            budget(workspace)
            destination = (
                workspace.root / "golden" / "lookups" / kind / source_path.name
            )
            if source == "timezones":
                destination.parent.mkdir(parents=True, exist_ok=True)
                if not destination.exists():
                    os.link(source_path, destination)
                record = {**file_record(destination), "rows": part["rows"]}
                if record["sha256"] != part["sha256"]:
                    raise ValueError("Timezone hardlink does not match the source")
            else:
                schema = pq.read_schema(source_path)
                for field in [
                    *strings("country_id place_id link_status link_method"),
                    pa.field("place_ids", pa.list_(pa.string())),
                ]:
                    schema = schema.append(field)
                record = parquet(
                    destination,
                    linked_rows(
                        source_path,
                        kind,
                        inputs,
                        countries,
                        codes,
                        index=index,
                        phone=phone,
                    ),
                    schema,
                )
            record.update(kind=kind)
            if source != "timezones":
                counts: Counter[str] = Counter()
                with pq.ParquetFile(destination) as file:
                    for batch in file.iter_batches(
                        columns=["link_status"], batch_size=8192
                    ):
                        counts.update(
                            str(value) for value in batch.column(0).to_pylist()
                        )
                record["counts"] = dict(counts)
            ledger.complete(
                "golden.static", unit, digest, [destination], metadata={"table": record}
            )
            result.append(record)
        print(f"static {source}: complete", flush=True)
    return result
