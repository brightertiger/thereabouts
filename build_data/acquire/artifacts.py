"""Hash records and immutable verification reports used by every manifest."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from .io import fingerprint, sha256_file, write_json
from .workspace import Workspace


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return cast(dict[str, Any], value)


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def file_records(paths: Iterable[Path]) -> list[dict[str, Any]]:
    return [file_record(path) for path in sorted(set(p.resolve() for p in paths))]


def verify_files(records: Iterable[Mapping[str, Any]]) -> None:
    for record in records:
        path = Path(record["path"])
        if (
            path.stat().st_size != record["size"]
            or sha256_file(path) != record["sha256"]
        ):
            raise ValueError(f"Artifact verification failed: {path}")


def publish_report(
    workspace: Workspace, source: str, report: Mapping[str, object]
) -> Path:
    """Keep an immutable report so failed reruns cannot invalidate a manifest."""
    root = workspace.normalized(source)
    path = root / f"verification-{fingerprint(report)}.json"
    if not path.exists():
        write_json(path, report)
    latest = root / "verification.json"
    if not latest.exists() or read_json(latest) != report:
        write_json(latest, report)
    return path
