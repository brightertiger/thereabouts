"""Timezone memberships and code/telephone joins independent of cell building."""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pyarrow as pa

from build_data.acquire import Ledger, Workspace
from build_data.acquire.artifacts import file_record
from build_data.acquire.io import fingerprint
from build_data.acquire.ledger import read_units
from build_data.acquire.manifests import load_manifest
from build_data.reconcile.common import Row, connect, rows, unpack

from .inputs import Inputs
from .schemas import strings
from .storage import budget, parquet


def code_map(inputs: Inputs) -> tuple[set[str], dict[str, set[str]]]:
    countries: set[str] = set()
    codes: dict[str, set[str]] = {}
    for cc, path in inputs.paths.items():
        db = connect(path, readonly=True)
        try:
            for identity, role, data in db.execute(
                "SELECT id,role,data FROM entities WHERE role IN ('country','state')"
            ):
                e = unpack(data)
                if role == "country":
                    countries.add(cc)
                elif e["code"]:
                    codes.setdefault("iso:" + e["code"], set()).add(identity)
            for identity, data in db.execute("SELECT entity,data FROM state_codes"):
                code = unpack(data)["geonames_admin1"]
                if code:
                    codes.setdefault(f"geonames:{cc}.{code}", set()).add(identity)
        finally:
            db.close()
    return countries, codes


def linked_rows(
    path: Path,
    kind: str,
    inputs: Inputs,
    countries: set[str],
    codes: dict[str, set[str]],
) -> Iterator[Row]:
    for row in rows(path):
        cc = row.get("country_code", row.get("territory"))
        country_id = f"country:{cc}" if cc in countries else None
        options = []
        if kind == "subdivisions":
            system = "iso" if row["code_system"].startswith("ISO") else "geonames"
            options = sorted(codes.get(f"{system}:{row['code']}", set()))
        elif kind == "phone_prefixes":
            options = [f"country:{c}" for c in row["country_codes"] if c in countries]
        elif country_id:
            options = [country_id]
        expected = row.get("country_codes", [cc])
        pending = any(
            c
            and c not in inputs.countries
            and c != "001"
            and (inputs.expected is None or c in inputs.expected)
            for c in expected
        )
        if kind == "phone_prefixes" and len(options) == 1 and not pending:
            country_id = options[0]
        status = (
            "pending"
            if pending
            else "matched"
            if len(options) == 1
            else "ambiguous"
            if options
            else "unmatched"
        )
        yield {
            **row,
            "country_id": country_id,
            "place_id": options[0] if len(options) == 1 and not pending else None,
            "place_ids": options,
            "link_status": status,
        }


def export(workspace: Workspace, inputs: Inputs) -> list[Row]:
    import pyarrow.parquet as pq

    ledger = Ledger(workspace.ledger_path)
    previous = {
        r["unit_id"]: r for r in read_units(workspace.ledger_path, "golden.static")
    }
    countries, codes = code_map(inputs)
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
                    "static": 3,
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
                    *strings("country_id place_id link_status"),
                    pa.field("place_ids", pa.list_(pa.string())),
                ]:
                    schema = schema.append(field)
                record = parquet(
                    destination,
                    linked_rows(source_path, kind, inputs, countries, codes),
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
