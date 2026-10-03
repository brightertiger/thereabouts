"""Explicit release attribution and copies of verified source notices."""

import re
from pathlib import Path

from build_data.acquire.io import atomic_output
from thereabouts.packs.jsonio import check_file, parse, string
from thereabouts.packs.metadata import sources

from .checkpoints import file_record
from .snapshot import Row, Snapshot


def release_metadata(path: Path) -> Row:
    value = parse(path.read_bytes())
    if set(value) != {"data_version", "catalogue_epoch", "sources", "notices"}:
        raise ValueError(
            "Release metadata requires data_version, catalogue_epoch, sources, notices"
        )
    for name in ("data_version", "catalogue_epoch"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", string(value[name])):
            raise ValueError("Version and epoch must be portable identifiers")
    sources(value["sources"])
    if not value["notices"]:
        raise ValueError("Release metadata must include licence notices")
    for record in value["notices"]:
        if set(record) != {"path", "size", "sha256"}:
            raise ValueError("Notice records require path, size and sha256 only")
        check_file(path.parent, record, full=True)
    return value


def notices(snapshot: Snapshot, release: Row, metadata: Path, pack: Path) -> list[Row]:
    records = []
    inputs = [(metadata.parent, r) for r in release["notices"]]
    inputs += [
        (snapshot.root, r)
        for r in snapshot.manifest["verification_artifacts"]
        if Path(r["path"]).name in {"DATA_LICENSES.md", "DATASET_CARD.md"}
    ]
    golden_names = {
        Path(r["path"]).name for r in snapshot.manifest["verification_artifacts"]
    }
    if (
        not {"DATA_LICENSES.md", "DATASET_CARD.md"} <= golden_names
        or len(inputs) != len(release["notices"]) + 2
    ):
        raise ValueError(
            "Golden verification must include licence notices and dataset card"
        )
    for i, (root, record) in enumerate(inputs):
        source = check_file(root, record, full=True)
        target = pack / "notices" / f"{i:03d}-{source.name}"
        with atomic_output(target, lambda p: None) as temporary:
            temporary.write_bytes(source.read_bytes())
        records.append(file_record(target, pack, kind="notice"))
    return records
