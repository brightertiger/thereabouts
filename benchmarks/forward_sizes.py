"""Account for compressed query data, cold evidence and fixed pack overhead."""

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from typing import Any

from benchmarks.core_read_path import ROOT

FAMILIES = ("postal", "airports", "locode", "phone", "ip", "plates")
CEILINGS = {
    "ip": 16,
    "postal": 14,
    "airports": 40,
    "locode": 40,
    "phone": 40,
    "plates": 40,
}
COLD = {
    "airport_evidence",
    "airport_assertions",
    "evidence",
    "evidence4",
    "evidence6",
    "details",
    "evidence_strings",
    "plate_format_evidence",
    "plate_code_evidence",
}


def measure(pack: Path) -> dict[str, Any]:
    """Count the actual compressed section bytes, without decoding or extrapolating."""
    manifest = json.loads((pack / "manifest.json").read_text())
    schema = manifest.get("forward_columns") or manifest["plate_columns"]
    blocks: dict[str, int] = {}
    roles: dict[str, int] = {}
    for artifact in manifest["files"]:
        role = artifact["kind"]
        roles[role] = roles.get(role, 0) + artifact["size"]
        with (pack / artifact["path"]).open("rb") as stream:
            header = stream.read(96)
        if len(header) >= 96 and header[:8] == b"THEREPK\0":
            kind = struct.unpack_from("<I", header, 16)[0]
            if kind in (9, 10):
                blocks[role] = (
                    blocks.get(role, 0) + struct.unpack_from("<Q", header, 80)[0]
                )
    hot = sum(n for role, n in blocks.items() if role not in COLD)
    cold = sum(n for role, n in blocks.items() if role in COLD)
    rows = schema["source_rows"]
    return {
        "source_rows": rows,
        "compressed_query_bytes": hot,
        "compressed_evidence_bytes": cold,
        "query_bytes_per_row": hot / rows,
        "all_compressed_bytes_per_row": (hot + cold) / rows,
        "budget_ceiling_bytes_per_row": CEILINGS[manifest["family"]],
        "budget_passed": (hot + cold) / rows <= CEILINGS[manifest["family"]],
        "compressed_bytes_by_role": blocks,
        "artifact_bytes_by_role": roles,
        "pack_bytes": sum(p.stat().st_size for p in pack.iterdir() if p.is_file()),
    }


def estimate(pack: Path, world_rows: int, rows: int) -> dict[str, Any]:
    """Scale data (including evidence and FSTs), adding measured supporting tables."""
    manifest = json.loads((pack / "manifest.json").read_text())
    roles: dict[str, int] = {}
    for artifact in manifest["files"]:
        roles[artifact["kind"]] = roles.get(artifact["kind"], 0) + artifact["size"]
    fixed = sum(roles.get(k, 0) for k in ("catalogue", "metadata"))
    supporting_scope = "sample; world catalogue growth is not modelled"
    measured = ROOT / f"docs/measurements/{manifest['family']}-world-manifest.json"
    provenance = manifest["inputs"]["options"].get("input_provenance", {})
    if measured.exists():
        world = json.loads(measured.read_text())
        if (
            world["inputs"]["manifest_sha256"]
            == provenance.get("golden_manifest_sha256")
            and world["storage"]["source_rows"] == world_rows
        ):
            fixed = sum(
                world["storage"][k] for k in ("catalogue_bytes", "metadata_bytes")
            )
            supporting_scope = (
                f"measured world supporting tables, writer {world['inputs']['writer']}"
            )
    data = sum(
        n for k, n in roles.items() if k not in {"catalogue", "metadata", "notice"}
    )
    return {
        "estimated_world_bytes": round(data / rows * world_rows) + fixed,
        "data_artifact_bytes_per_row": data / rows,
        "measured_catalogue_metadata_bytes": fixed,
        "supporting_tables_scope": supporting_scope,
        "estimate_method": (
            "all data artifacts (compressed query and evidence, FSTs, directories, "
            "framing) / source rows * world rows + measured catalogue/metadata; "
            + supporting_scope
        ),
    }


def update_status(values: dict[str, Any]) -> None:
    """Replace only this script's delimited table."""
    start, end = "<!-- forward-format:start -->", "<!-- forward-format:end -->"
    lines = [
        (
            "| Family | Old data-shard B/row | Query blocks B/row | "
            "All compressed B/row | Sample pack bytes | Estimated world bytes |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for family, value in values.items():
        old = value.get("before", {}).get("data_bytes_per_row")
        lines.append(
            f"| {family} | {old:.2f} | {value['query_bytes_per_row']:.2f} | "
            f"{value['all_compressed_bytes_per_row']:.2f} | {value['pack_bytes']:,} | "
            f"{value['estimated_world_bytes']:,} |"
            if old is not None
            else f"| {family} | — | {value['query_bytes_per_row']:.2f} | "
            f"{value['all_compressed_bytes_per_row']:.2f} | {value['pack_bytes']:,} | "
            f"{value['estimated_world_bytes']:,} |"
        )
    section = start + "\n" + "\n".join(lines) + "\n" + end
    path = ROOT / "docs/CLIENT_STATUS.md"
    text = path.read_text()
    if start in text:
        a, b = text.index(start), text.index(end) + len(end)
        text = text[:a] + section + text[b:]
    else:
        text += "\n## Forward format measurements\n\n" + section + "\n"
    path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-ref", default="557baff")
    parser.add_argument("--series", default="forward_format")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if query plus evidence blocks exceed any family ceiling",
    )
    args = parser.parse_args()
    output = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(output.read_text())
    previous = data.get("forward_format", {})
    values = {}
    for family in FAMILIES:
        pack = ROOT / f"tests/fixtures/packs/{family}-sample"
        value = measure(pack)
        manifest = json.loads((pack / "manifest.json").read_text())
        world_rows = manifest["inputs"]["options"]["input_provenance"][
            "world_source_rows"
        ]
        value.update(estimate(pack, world_rows, value["source_rows"]))
        if args.baseline:
            old_path = args.baseline / f"{family}-sample"
            manifest = json.loads((old_path / "manifest.json").read_text())
            shards = sum(
                a["size"]
                for a in manifest["files"]
                if a["kind"] in {"exact", "trie", "intervals", "plates"}
            )
            # The historical denominator belongs to the historical source extract,
            # even when the current sample has grown or gained named examples.
            source_text = subprocess.check_output(
                [
                    "git",
                    "show",
                    f"{args.baseline_ref}:tests/fixtures/{family}-source.json",
                ],
                cwd=ROOT,
                text=True,
            )
            source_rows = len(json.loads(source_text)["rows"])
            value["before"] = {
                "source_rows": source_rows,
                "data_shard_bytes": shards,
                "data_bytes_per_row": shards / source_rows,
                "pack_bytes": sum(p.stat().st_size for p in old_path.iterdir()),
                "manifest_sha256": hashlib.sha256(
                    (old_path / "manifest.json").read_bytes()
                ).hexdigest(),
            }
        elif family in previous and "before" in previous[family]:
            value["before"] = previous[family]["before"]
        values[family] = value
    data[args.series] = values
    output.write_text(json.dumps(data, indent=2) + "\n")
    if args.series == "forward_format":
        update_status(values)
    print(json.dumps(values, indent=2))
    if args.check and any(not value["budget_passed"] for value in values.values()):
        raise SystemExit("Compressed query/evidence size gate failed")


if __name__ == "__main__":
    main()
