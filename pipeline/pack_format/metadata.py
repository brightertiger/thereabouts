"""Serving manifest validation without reading payload contents on open."""

from pathlib import Path
from typing import Any

from .errors import CorruptPackError, UnsupportedPackError
from .jsonio import (
    check_file,
    checksum,
    digest,
    integer,
    parse,
    relative_name,
    sha256,
    string,
)
from .keys import FAMILIES, normalization
from .layout import BLOCK_COUNT, UINT32_MAX


def sources(value: Any) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError("Explicit source attribution is required")
    identities = set()
    fields = {
        "source",
        "release",
        "license",
        "attribution",
        "source_url",
        "license_url",
    }
    for source in value:
        if not isinstance(source, dict) or set(source) != fields:
            raise ValueError("Invalid source attribution fields")
        for key in fields:
            string(source[key])
        identity = (source["source"], source["release"])
        if identity in identities:
            raise ValueError("Duplicate source release")
        identities.add(identity)


def read_manifest(root: Path, *, full: bool = False) -> dict[str, Any]:
    try:
        manifest_path = root / "manifest.json"
        value = parse(manifest_path.read_bytes())
        if "manifest_sha256" in value:
            raise ValueError(
                "Manifest identity is the hash of its bytes, not a self-hash"
            )
        for field in ("major", "minor", "required_features"):
            integer(value["format"][field])
        if value["schema"] != "thereabouts-pack-1" or value["format"] != {
            "major": 1,
            "minor": 0,
            "required_features": 0,
        }:
            raise UnsupportedPackError("Expected thereabouts-pack-1 format 1.0")
        if value["family"] not in FAMILIES:
            raise UnsupportedPackError("Unsupported pack family")
        exact = value["family"] != "reverse"
        if exact:
            normalization(value["key_normalization"])
            if integer(value["unindexed_rows"]) > integer(value["source_rows"]):
                raise ValueError("Invalid lookup source row accounting")
            if value["candidate_policy"] != "source-observations-1":
                raise UnsupportedPackError("Unsupported candidate policy")
        if (
            integer(value["reference_resolution"]) != 8
            or integer(value["block_resolution"]) != 3
        ):
            raise UnsupportedPackError("Unsupported H3 reference resolutions")
        if value["minimum_reader"] != "0.1.0":
            raise UnsupportedPackError("Pack requires a different reader version")
        for key in ("data_version", "catalogue_epoch", "h3_version"):
            string(value[key])
        if not value["h3_version"].startswith("4."):
            raise UnsupportedPackError("Unsupported H3 major version")
        for key in ("golden_sha256", "policy_sha256", "export_fingerprint"):
            checksum(value[key])
        nearest = value["nearest"]
        if (
            integer(nearest["distant_over_m"]) >= integer(nearest["cutoff_m"], 1)
            or nearest["exact_distance"] is not False
        ):
            raise ValueError("Invalid nearest-distance semantics")
        export = value["export"]
        if not isinstance(export, dict) or not isinstance(
            export["implementation"], dict
        ):
            raise ValueError("Invalid exporter identity")
        for name, code_hash in export["implementation"].items():
            relative_name(string(name))
            checksum(code_hash)
        for record in export["release"]["notices"]:
            relative_name(string(record["path"]))
            integer(record["size"])
            checksum(record["sha256"])
        if (
            digest(export) != value["export_fingerprint"]
            or export["golden_sha256"] != value["golden_sha256"]
        ):
            raise ValueError("Mismatched export identity")
        for field in ("data_version", "catalogue_epoch", "sources"):
            if value[field] != export["release"][field]:
                raise ValueError("Mismatched release metadata")
        if value["dependencies"] != []:
            raise UnsupportedPackError("Pack dependencies are unsupported")
        sources(value["sources"])
        count = integer(value["place_count"])
        if count > UINT32_MAX:
            raise ValueError("Catalogue exceeds uint32 references")
        records = value["files"]
        if not isinstance(records, list) or not records:
            raise ValueError("Missing payload inventory")
        seen: set[str] = set()
        next_place, last_block = 1, -1
        spatial = exact_shards = 0
        last_key = b""
        for record in records:
            name = string(record["path"])
            if name in seen or name == "manifest.json":
                raise ValueError("Duplicate or reserved artifact path")
            seen.add(name)
            check_file(root, record, full=full)
            kind = record["kind"]
            if kind == "catalogue":
                first = integer(record["first_id"], 1)
                rows = integer(record["count"], 1)
                if first != next_place:
                    raise ValueError("Noncontiguous catalogue shard IDs")
                next_place += rows
            elif kind == "exact":
                if not exact:
                    raise ValueError("Exact payload in reverse pack")
                first_key = string(record["first_key"]).encode("utf-8")
                end_key = string(record["last_key"]).encode("utf-8")
                if not last_key < first_key <= end_key:
                    raise ValueError("Overlapping exact-key shards")
                integer(record["count"], 1)
                integer(record["max_record_bytes"], 1)
                last_key = end_key
                exact_shards += 1
            elif kind == "cells":
                if exact:
                    raise ValueError("Cell payload in exact-key pack")
                first, last = (
                    integer(record["first_block"]),
                    integer(record["last_block"]),
                )
                if not last_block < first <= last < BLOCK_COUNT:
                    raise ValueError("Overlapping or unordered cell shards")
                last_block = last
                spatial += 1
            elif kind != "notice":
                raise UnsupportedPackError(f"Unsupported artifact kind: {kind}")
        if next_place != count + 1 or not (exact_shards if exact else spatial):
            raise ValueError("Incomplete catalogue or spatial inventory")
        if value["coverage"] not in (("keys",) if exact else ("world", "blocks")):
            raise ValueError("Unknown coverage declaration")
        notices = value["notices"]
        if (
            not isinstance(notices, list)
            or not notices
            or len(set(notices)) != len(notices)
        ):
            raise ValueError("Missing or repeated notices")
        if set(notices) != {r["path"] for r in records if r["kind"] == "notice"}:
            raise ValueError("Notices must be checksummed artifacts")
        value["manifest_sha256"] = sha256(manifest_path)
        return value
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CorruptPackError(f"Invalid serving manifest: {exc}") from exc
