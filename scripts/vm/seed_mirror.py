#!/usr/bin/env python3
"""Seed the content-addressed raw mirror, raw/sha256/<sha256>, from pins.lock.

--origin laptop  verify files under data/raw/<source>/<name> and upload them
                 (run on the laptop).
--origin legacy  copy files still held under <mirror_base>/<name> to a temporary
                 file, verify them against the pin and upload them (run on the VM,
                 which is in the bucket's region).
--origin merge   combine the two custody files with a fresh mirror listing into
                 the final report.

Every run is idempotent and resumable: keys that already hold an object of the
pinned size are skipped, an interrupted upload is retried, and the custody file
keeps what earlier runs proved. Only `gcloud storage` is used. Nothing is ever
deleted from the bucket, and an existing object of the wrong size is reported as
a conflict rather than overwritten.
"""

import argparse
import base64
import concurrent.futures
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
BUCKET = "gs://pyofflinegeocoder-summer-sector-488705-m8"
CHUNK = 1 << 20


@dataclass(frozen=True)
class Pinned:
    source: str
    name: str
    sha256: str
    size: int
    base: str | None

    @property
    def id(self) -> str:
        return f"{self.source}/{self.name}"

    @property
    def legacy(self) -> str | None:
        return f"{self.base}/{self.name}" if self.base else None


@dataclass(frozen=True)
class Remote:
    size: int
    md5: str | None


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def log(message: str) -> None:
    print(f"{now()} {message}", file=sys.stderr, flush=True)


def load_pins(path: Path) -> tuple[list[Pinned], list[str]]:
    lock = yaml.safe_load(path.read_text())
    pins: list[Pinned] = []
    empty: list[str] = []
    for source, entry in lock.items():
        base = ((entry.get("metadata") or {}).get("mirror_base") or "").rstrip(
            "/"
        ) or None
        if not entry.get("files"):
            empty.append(source)
        for item in entry.get("files") or []:
            pins.append(
                Pinned(source, item["name"], item["sha256"], int(item["size"]), base)
            )
    return pins, empty


def gcloud(*args: str, retries: int = 4) -> subprocess.CompletedProcess[str]:
    delay = 5.0
    for attempt in range(retries + 1):
        result = subprocess.run(
            ["gcloud", "storage", *args], capture_output=True, text=True
        )
        if result.returncode == 0:
            return result
        if attempt == retries or "matched no objects" in result.stderr:
            raise RuntimeError(
                result.stderr.strip() or f"gcloud exited {result.returncode}"
            )
        time.sleep(delay)
        delay = min(delay * 2, 120)
    raise AssertionError("unreachable")


def listing(pattern: str) -> dict[str, Remote]:
    """Objects under a gs:// pattern keyed by url without its generation suffix."""
    try:
        text = gcloud("ls", "--json", pattern).stdout
    except RuntimeError as error:
        if "matched no objects" in str(error):
            return {}
        raise
    found: dict[str, Remote] = {}
    for item in json.loads(text or "[]"):
        if item.get("type") != "cloud_object":
            continue
        meta = item["metadata"]
        found[item["url"].split("#")[0]] = Remote(
            int(meta["size"]), meta.get("md5Hash")
        )
    return found


def mirror_key(bucket: str, sha256: str) -> str:
    return f"{bucket}/raw/sha256/{sha256}"


def digests(path: Path) -> tuple[str, str]:
    """sha256 (hex) and md5 (base64, the form GCS reports) of a file."""
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            sha.update(block)
            md5.update(block)
    return sha.hexdigest(), base64.b64encode(md5.digest()).decode()


class Custody:
    """Per-file records of what this side proved, persisted atomically."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.dirty = 0
        self.saved = time.monotonic()
        self.records: dict[str, dict[str, Any]] = {}
        if path.exists():
            self.records = json.loads(path.read_text())["records"]

    def get(self, pin: Pinned) -> dict[str, Any] | None:
        return self.records.get(pin.id)

    def put(self, pin: Pinned, key: str, **fields: object) -> None:
        with self.lock:
            record = {
                "source": pin.source,
                "name": pin.name,
                "sha256": pin.sha256,
                "size": pin.size,
                "key": key,
                "origin": None,
                "status": "pending",
                "local_verified": False,
                "md5": None,
                "detail": "",
                **fields,
                "updated": now(),
            }
            self.records[pin.id] = record
            self.dirty += 1
            if time.monotonic() - self.saved > 5:
                self._write()

    def save(self) -> None:
        with self.lock:
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(descriptor, "w") as handle:
            json.dump(
                {"saved": now(), "records": self.records},
                handle,
                indent=1,
                sort_keys=True,
            )
        os.replace(temporary, self.path)
        self.dirty = 0
        self.saved = time.monotonic()


def groups(pins: list[Pinned]) -> dict[str, list[Pinned]]:
    result: dict[str, list[Pinned]] = defaultdict(list)
    for pin in pins:
        result[pin.sha256].append(pin)
    for sha, members in result.items():
        if len({member.size for member in members}) != 1:
            raise ValueError(f"Pins disagree on the size of {sha}: {members}")
    return dict(result)


def finish(
    custody: Custody,
    members: list[Pinned],
    key: str,
    proven: Pinned,
    origin: str,
    status: str,
    md5: str,
) -> None:
    """Record every pin sharing these bytes; the others inherit the proof."""
    for member in members:
        detail = "" if member == proven else f"same sha256 as {proven.id}"
        custody.put(
            member,
            key,
            origin=origin,
            status=status,
            local_verified=True,
            md5=md5,
            detail=detail,
        )


def fail(
    custody: Custody, members: list[Pinned], key: str, status: str, detail: str
) -> None:
    for member in members:
        previous = custody.get(member)
        if previous and previous["local_verified"]:
            continue  # an earlier run already proved these bytes
        custody.put(member, key, status=status, detail=detail)


def upload(path: Path, key: str) -> None:
    gcloud("cp", "--no-clobber", str(path), key)


def seed_laptop(args: argparse.Namespace, pins: list[Pinned]) -> int:
    custody = Custody(args.custody)
    mirror = listing(f"{args.bucket}/raw/sha256/**")
    log(f"mirror holds {len(mirror)} objects")

    def work(sha: str, members: list[Pinned]) -> str:
        key = mirror_key(args.bucket, sha)
        notes: list[str] = []
        for member in members:
            path = args.raw_dir / member.source / member.name
            if not path.is_file():
                notes.append(f"{member.id}: not in {args.raw_dir}")
                continue
            if path.stat().st_size != member.size:
                notes.append(
                    f"{member.id}: size {path.stat().st_size} != pinned {member.size}"
                )
                continue
            actual, md5 = digests(path)
            if actual != sha:
                notes.append(f"{member.id}: sha256 {actual} != pinned")
                continue
            existing = mirror.get(key)
            if existing and existing.size != member.size:
                fail(
                    custody,
                    members,
                    key,
                    "conflict",
                    f"mirror object has {existing.size} bytes",
                )
                return "conflict"
            if existing:
                finish(custody, members, key, member, "laptop", "present", md5)
                return "present"
            if args.dry_run:
                return "would-upload"
            upload(path, key)
            finish(custody, members, key, member, "laptop", "uploaded", md5)
            return "uploaded"
        status = "mismatch" if any("!=" in note for note in notes) else "absent"
        fail(custody, members, key, status, "; ".join(notes))
        return status

    return run_groups(args, pins, custody, work)


def seed_legacy(args: argparse.Namespace, pins: list[Pinned]) -> int:
    custody = Custody(args.custody)
    mirror = listing(f"{args.bucket}/raw/sha256/**")
    log(f"mirror holds {len(mirror)} objects")
    legacy: dict[str, Remote] = {}
    bases = sorted({pin.base for pin in pins if pin.base})
    for base in bases:
        legacy.update(listing(f"{base}/**"))
    log(f"legacy prefixes {bases} hold {len(legacy)} objects")
    args.work_dir.mkdir(parents=True, exist_ok=True)

    def work(sha: str, members: list[Pinned]) -> str:
        key = mirror_key(args.bucket, sha)
        existing = mirror.get(key)
        if existing and existing.size != members[0].size:
            fail(
                custody,
                members,
                key,
                "conflict",
                f"mirror object has {existing.size} bytes",
            )
            return "conflict"
        if existing:
            for member in members:
                if not custody.get(member):
                    custody.put(
                        member, key, status="present", detail="already in the mirror"
                    )
            return "present"
        notes: list[str] = []
        for member in members:
            source_url = member.legacy
            remote = legacy.get(source_url) if source_url else None
            if source_url is None or remote is None:
                notes.append(f"{member.id}: no legacy object at {source_url}")
                continue
            if remote.size != member.size:
                notes.append(
                    f"{member.id}: legacy size {remote.size} != pinned {member.size}"
                )
                continue
            if args.dry_run:
                return "would-copy"
            temporary = args.work_dir / f"{sha}.download"
            temporary.unlink(missing_ok=True)
            try:
                gcloud("cp", source_url, str(temporary))
                actual, md5 = digests(temporary)
                if actual != sha or temporary.stat().st_size != member.size:
                    notes.append(f"{member.id}: downloaded sha256 {actual} != pinned")
                    continue
                upload(temporary, key)
            finally:
                temporary.unlink(missing_ok=True)
            finish(custody, members, key, member, "legacy", "uploaded", md5)
            return "uploaded"
        status = "mismatch" if any("!=" in note for note in notes) else "absent"
        fail(custody, members, key, status, "; ".join(notes))
        return status

    return run_groups(args, pins, custody, work)


def run_groups(
    args: argparse.Namespace,
    pins: list[Pinned],
    custody: Custody,
    work: Callable[[str, list[Pinned]], str],
) -> int:
    todo = groups(pins)
    counts: dict[str, int] = defaultdict(int)
    done = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            futures = {
                pool.submit(work, sha, members): sha for sha, members in todo.items()
            }
            for future in concurrent.futures.as_completed(futures):
                sha = futures[future]
                try:
                    outcome = future.result()
                except Exception as error:  # a failed key must not stop the others
                    outcome = "error"
                    fail(
                        custody,
                        todo[sha],
                        mirror_key(args.bucket, sha),
                        "error",
                        f"{type(error).__name__}: {error}"[:500],
                    )
                    log(f"error {sha}: {error}"[:300])
                counts[outcome] += 1
                done += 1
                if done % 50 == 0 or done == len(todo):
                    log(f"{done}/{len(todo)} keys: {dict(counts)}")
    finally:
        custody.save()
    log(f"finished: {dict(counts)}")
    return 0 if not counts.get("error") else 1


def merge(args: argparse.Namespace, pins: list[Pinned], empty: list[str]) -> int:
    stores = {
        "laptop": Custody(args.laptop_custody).records
        if args.laptop_custody.exists()
        else {},
        "legacy": Custody(args.legacy_custody).records
        if args.legacy_custody.exists()
        else {},
    }
    mirror = listing(f"{args.bucket}/raw/sha256/**")
    files: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for pin in pins:
        key = mirror_key(args.bucket, pin.sha256)
        proof = None
        for origin in ("laptop", "legacy"):
            record = stores[origin].get(pin.id)
            if record and record["local_verified"]:
                proof = record
                break
        remote = mirror.get(key)
        problems = []
        if proof is None:
            seen = [
                f"{origin}: {record['status']} {record['detail']}".strip()
                for origin, store in stores.items()
                if (record := store.get(pin.id))
            ]
            problems.append(
                "no origin verified the bytes against the pin"
                + (f" ({'; '.join(seen)})" if seen else "")
            )
        if remote is None:
            problems.append("mirror key is absent")
        elif remote.size != pin.size:
            problems.append(f"mirror object has {remote.size} bytes")
        elif proof and proof["md5"] and remote.md5 and proof["md5"] != remote.md5:
            problems.append("mirror md5 differs from the verified bytes")
        entry: dict[str, Any] = {
            "source": pin.source,
            "name": pin.name,
            "sha256": pin.sha256,
            "size": pin.size,
            "key": key,
            "origin": proof["origin"] if proof else None,
            "verified": not problems,
        }
        if problems:
            entry["problems"] = problems
            missing.append(entry)
        files.append(entry)
    verified = [entry for entry in files if entry["verified"]]
    report = {
        "generated": now(),
        "bucket": args.bucket,
        "pins": str(args.pins),
        "pins_sha256": hashlib.sha256(args.pins.read_bytes()).hexdigest(),
        "summary": {
            "pinned_files": len(files),
            "unique_keys": len({entry["sha256"] for entry in files}),
            "verified": len(verified),
            "from_laptop": sum(entry["origin"] == "laptop" for entry in verified),
            "from_legacy": sum(entry["origin"] == "legacy" for entry in verified),
            "not_verified": len(missing),
            "bytes_verified": sum(entry["size"] for entry in verified),
        },
        "sources_without_files": empty,
        "files": files,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    log(f"wrote {args.out}: {report['summary']}")
    for entry in missing:
        reasons = "; ".join(entry["problems"])
        log(f"NOT VERIFIED {entry['source']}/{entry['name']}: {reasons}")
    return 0 if not missing else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--origin", choices=("laptop", "legacy", "merge"), required=True
    )
    parser.add_argument("--pins", type=Path, default=REPO / "pins.lock")
    parser.add_argument("--bucket", default=BUCKET)
    parser.add_argument(
        "--custody", type=Path, help="state file of this side (laptop, legacy)"
    )
    parser.add_argument(
        "--raw-dir", type=Path, default=REPO / "data/raw", help="laptop only"
    )
    parser.add_argument(
        "--work-dir", type=Path, help="legacy only: temporary downloads"
    )
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument(
        "--dry-run", action="store_true", help="verify and plan, upload nothing"
    )
    parser.add_argument("--laptop-custody", type=Path, help="merge only")
    parser.add_argument("--legacy-custody", type=Path, help="merge only")
    parser.add_argument("--out", type=Path, help="merge only: the final custody report")
    args = parser.parse_args()
    args.bucket = args.bucket.rstrip("/")
    pins, empty = load_pins(args.pins)
    keys = len({pin.sha256 for pin in pins})
    log(f"{len(pins)} pinned files, {keys} unique keys; sources without files: {empty}")
    if args.origin == "merge":
        if not (args.laptop_custody and args.legacy_custody and args.out):
            parser.error("merge needs --laptop-custody, --legacy-custody and --out")
        return merge(args, pins, empty)
    if not args.custody:
        parser.error("--custody is required")
    if args.origin == "laptop":
        return seed_laptop(args, pins)
    if not args.work_dir:
        parser.error("--work-dir is required for legacy")
    return seed_legacy(args, pins)


if __name__ == "__main__":
    sys.exit(main())
