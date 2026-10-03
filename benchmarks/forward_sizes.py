"""Account for compressed query data, cold evidence and fixed pack overhead."""

import argparse
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

from benchmarks.core_read_path import ROOT

FAMILIES = ("postal", "airports", "locode", "phone", "ip", "plates")
COLD = {
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
        "compressed_bytes_by_role": blocks,
        "artifact_bytes_by_role": roles,
        "pack_bytes": sum(p.stat().st_size for p in pack.iterdir() if p.is_file()),
    }


def update_status(values: dict[str, Any]) -> None:
    """Replace only this script's delimited table."""
    start, end = "<!-- forward-format:start -->", "<!-- forward-format:end -->"
    lines = [
        (
            "| Family | Old data-shard B/row | Query blocks B/row | "
            "All compressed B/row | Sample pack bytes |"
        ),
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for family, value in values.items():
        old = value.get("before", {}).get("data_bytes_per_row")
        lines.append(
            f"| {family} | {old:.2f} | {value['query_bytes_per_row']:.2f} | "
            f"{value['all_compressed_bytes_per_row']:.2f} | {value['pack_bytes']:,} |"
            if old is not None
            else f"| {family} | — | {value['query_bytes_per_row']:.2f} | "
            f"{value['all_compressed_bytes_per_row']:.2f} | {value['pack_bytes']:,} |"
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
    args = parser.parse_args()
    output = ROOT / "docs/CLIENT_CORE_MEASUREMENTS.json"
    data = json.loads(output.read_text())
    previous = data.get("forward_format", {})
    values = {}
    for family in FAMILIES:
        value = measure(ROOT / f"tests/fixtures/packs/{family}-sample")
        if args.baseline:
            old_path = args.baseline / f"{family}-sample"
            manifest = json.loads((old_path / "manifest.json").read_text())
            shards = sum(
                a["size"]
                for a in manifest["files"]
                if a["kind"] in {"exact", "trie", "intervals", "plates"}
            )
            value["before"] = {
                "data_shard_bytes": shards,
                "data_bytes_per_row": shards / value["source_rows"],
                "pack_bytes": sum(p.stat().st_size for p in old_path.iterdir()),
                "manifest_sha256": hashlib.sha256(
                    (old_path / "manifest.json").read_bytes()
                ).hexdigest(),
            }
        elif family in previous and "before" in previous[family]:
            value["before"] = previous[family]["before"]
        values[family] = value
    data["forward_format"] = values
    output.write_text(json.dumps(data, indent=2) + "\n")
    update_status(values)
    print(json.dumps(values, indent=2))


if __name__ == "__main__":
    main()
