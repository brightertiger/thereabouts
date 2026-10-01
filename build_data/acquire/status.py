"""Read-only acquisition progress, using manifests and checkpoint metadata."""

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .artifacts import read_json
from .io import fingerprint
from .ledger import read_units
from .lookup_catalog import LOOKUP_SOURCES
from .lookup_schemas import KINDS
from .manifests import MANIFEST_VERSION, inventory_path
from .offload import applies, state
from .workspace import SOURCES, Workspace


def _present(records: Sequence[dict[str, Any]]) -> bool:
    try:
        return all(
            Path(record["path"]).stat().st_size == record["size"] for record in records
        )
    except OSError:
        return False


def _expected(
    source: str, inventory: dict[str, Any], downloaded: list[dict[str, Any]]
) -> set[str]:
    if "specifications" in inventory:
        return set(inventory["specifications"])
    if source == "overture":
        return {obj["key"] for obj in inventory["objects"]}
    if source == "geonames":
        from .geonames_download import FILES

        return set(FILES)
    if source == "geoboundaries":
        return {
            f"{layer['boundaryISO']}-{layer['boundaryType']}"
            for layer in inventory["layers"]
        }
    from .osm_land import ARCHIVE

    expected = {ARCHIVE}
    for unit in downloaded:
        if unit["unit_id"] == ARCHIVE:
            for output in unit["outputs"]:
                if Path(output["path"]).name == "download-verification.json":
                    report = read_json(Path(output["path"]))
                    expected.update(
                        f"extract/{m['name']}" for m in report["zip_members"]
                    )
    return expected


def source_status(workspace: Workspace, source: str) -> dict[str, Any]:
    """Inspect sizes and markers only; do not hash datasets or initialize SQLite."""
    inventory_file = inventory_path(workspace, source)
    inventory = read_json(inventory_file) if inventory_file.exists() else None
    downloaded = read_units(workspace.ledger_path, f"{source}.download")
    expected = _expected(source, inventory, downloaded) if inventory else set()
    complete = [
        unit
        for unit in downloaded
        if unit["unit_id"] in expected and _present(unit["outputs"])
    ]
    raw_files = {
        record["path"]: record["size"]
        for unit in complete
        for record in unit["outputs"]
    }
    normalized = read_units(workspace.ledger_path, f"{source}.normalize")
    by_unit = {unit["unit_id"]: unit for unit in normalized}
    path = workspace.normalized(source) / "manifest.json"
    manifest = read_json(path) if path.exists() else {}
    current = manifest.get("manifest_version") == MANIFEST_VERSION
    commits = read_units(workspace.ledger_path, f"{source}.manifest")
    current = current and any(
        unit["inputs_hash"] == fingerprint(manifest) for unit in commits
    )
    rows: Counter[str] = Counter()
    parts: dict[str, int] = {}
    good = 0
    units = manifest.get("units", normalized)
    for unit in units:
        saved = by_unit.get(unit["unit_id"])
        if (
            saved
            and saved["inputs_hash"] == unit["inputs_hash"]
            and _present(saved["outputs"])
        ):
            good += 1
            if not current:
                metadata = saved["metadata"]
                if source == "osm_land":
                    rows["areas"] += metadata.get("rows", 0)
                elif source == "geoboundaries":
                    rows["areas"] += metadata.get("output_rows", 0)
                elif source in LOOKUP_SOURCES:
                    rows.update(metadata.get("output_rows", {}))
                    if source == "timezones":
                        rows["timezone_cells"] += metadata.get("cells", 0)
                        rows["timezones"] += metadata.get("geometry_parts", 0)
                        rows["zone_tables"] += metadata.get("rows", 0)
                elif source == "overture":
                    rows.update(metadata.get("output_rows", {}))
                elif "kind" in metadata:
                    rows[metadata["kind"]] += metadata.get("counts", {}).get("kept", 0)
            parts.update(
                {
                    r["path"]: r["size"]
                    for r in saved["outputs"]
                    if r["path"].endswith(".parquet")
                }
            )
    if current:
        for part in manifest["partitions"]:
            if parts.get(part["path"]) == part["size"]:
                rows[part["kind"]] += part["rows"]
        current = (
            good == len(units)
            and len(parts) == len(manifest["partitions"])
            and inventory is not None
            and manifest["source_release"] == inventory["source_release"]
            and _present([manifest["inventory"], *manifest["auxiliary"]])
        )
    return {
        "source": source,
        "download": "offloaded"
        if applies(workspace, source, manifest)
        else "complete"
        if expected and len(complete) == len(expected)
        else "incomplete",
        "download_units": len(complete),
        "expected_download_units": len(expected),
        "raw_bytes": sum(raw_files.values()),
        "normalize": "complete" if current else "incomplete",
        "normalized_units": good,
        "expected_normalized_units": len(units),
        "rows": dict(rows),
        "partitions": len(parts),
        "normalized_bytes": sum(parts.values()),
        "offload": state(workspace, source),
    }


def print_status(workspace: Workspace) -> None:
    for source in SOURCES:
        state = source_status(workspace, source)
        rows = ", ".join(
            f"{state['rows'][kind]:,} {kind}"
            for kind in ("areas", "places", "names", *KINDS)
            if kind in state["rows"]
        )
        print(
            f"{source}: download {state['download']} "
            f"({state['download_units']}/{state['expected_download_units']} units, "
            f"{state['raw_bytes']:,} bytes); normalize {state['normalize']} "
            f"({state['normalized_units']}/{state['expected_normalized_units']} units, "
            f"{state['partitions']} partitions, {state['normalized_bytes']:,} bytes)"
            + (f"; {rows}" if rows else "")
        )
