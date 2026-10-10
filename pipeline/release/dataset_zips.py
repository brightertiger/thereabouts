"""Deterministic stored zips of each dataset table, the dataset's GitHub transport.

GitHub release assets are flat and under 2 GiB, so each top-level dataset
directory (a table) ships as ``dataset-<table>.zip``, split into
``dataset-<table>-001.zip``, ``-002``... when one zip would exceed the asset
limit. Members keep their dataset-relative paths, so extracting every zip into
``dataset/<version>/`` rebuilds the tree. Zips are stored (Parquet is already
compressed), sorted, dated 1980-01-01 and free of extra fields, so a rerun
writes the same bytes and an interrupted upload resumes against the same
digests. Every zip written here is read back by the clients' Rust reader.
"""

import hashlib
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

from pipeline.runtime.jsonio import atomic_output, sha256_file
from pipeline.runtime.paths import located
from pipeline.runtime.resources import ResourceGuard

from .bundle import transport

LOCAL, CENTRAL, END = 0x04034B50, 0x02014B50, 0x06054B50
LOCAL_BYTES, CENTRAL_BYTES, END_BYTES = 30, 46, 22
VERSION = 20
MADE_BY = 3 << 8 | VERSION
UTF8 = 0x0800
# 1980-01-01 00:00 in MS-DOS date and time fields.
DOS_DATE, DOS_TIME = 0x21, 0
REGULAR_FILE = 0o100644 << 16
MAX_ENTRIES = 0xFFFF
MAX_PARTS = 999
TABLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


@dataclass(frozen=True)
class Member:
    path: str
    size: int
    sha256: str

    @property
    def encoded(self) -> bytes:
        return self.path.encode()

    @property
    def cost(self) -> int:
        """Bytes this member adds: local header, name, data and central record."""
        return LOCAL_BYTES + CENTRAL_BYTES + 2 * len(self.encoded) + self.size


@dataclass(frozen=True)
class TableZip:
    name: str
    table: str
    members: tuple[Member, ...]

    @property
    def size(self) -> int:
        return END_BYTES + sum(member.cost for member in self.members)

    @property
    def unpacked_size(self) -> int:
        return sum(member.size for member in self.members)


def plan(files: list[Member], max_bytes: int) -> list[TableZip]:
    """Group dataset files by table; split a table only when one zip is too large."""
    tables: dict[str, list[Member]] = {}
    for member in sorted(files, key=lambda item: item.path):
        table, separator, _ = member.path.partition("/")
        if not separator:
            raise ValueError(f"Only table files are zipped: {member.path}")
        if not TABLE.fullmatch(table):
            raise ValueError(f"Dataset table name is not a release asset name: {table}")
        if END_BYTES + member.cost > max_bytes:
            raise ValueError(
                f"Dataset file exceeds one release asset ({max_bytes} bytes): "
                + member.path
            )
        tables.setdefault(table, []).append(member)
    zips = []
    for table, members in sorted(tables.items()):
        whole = TableZip(f"dataset-{table}.zip", table, tuple(members))
        if whole.size <= max_bytes and len(members) <= MAX_ENTRIES:
            zips.append(whole)
            continue
        parts: list[list[Member]] = [[]]
        size = END_BYTES
        for member in members:
            if parts[-1] and (
                size + member.cost > max_bytes or len(parts[-1]) == MAX_ENTRIES
            ):
                parts.append([])
                size = END_BYTES
            parts[-1].append(member)
            size += member.cost
        if len(parts) > MAX_PARTS:
            raise ValueError(f"Dataset table needs over {MAX_PARTS} zips: {table}")
        zips += [
            TableZip(f"dataset-{table}-{number:03d}.zip", table, tuple(part))
            for number, part in enumerate(parts, 1)
        ]
    return zips


def build(
    zips: list[TableZip],
    dataset: Path,
    directory: Path,
    guard: ResourceGuard | None = None,
    read_bytes: int = 1 << 20,
) -> dict[str, Path]:
    """Write (or reuse) every zip under `directory`, each checked by the Rust reader."""
    written = {}
    for item in zips:
        target = directory / item.name
        if not (target.is_file() and target.stat().st_size == item.size):
            if guard is not None:
                guard.admit(item.size)
            try:
                with atomic_output(target) as temporary:
                    write(item, dataset, temporary, read_bytes)
                    verify(temporary, item)
            finally:
                if guard is not None:
                    guard.release(item.size)
        verify(target, item)
        written[item.name] = target
    return written


def write(item: TableZip, dataset: Path, target: Path, read_bytes: int) -> None:
    central = bytearray()
    with target.open("wb") as out:
        for member in item.members:
            name = member.encoded
            flags = 0 if name.isascii() else UTF8
            offset = out.tell()
            out.write(
                struct.pack(
                    "<IHHHHHIIIHH",
                    LOCAL,
                    VERSION,
                    flags,
                    0,
                    DOS_TIME,
                    DOS_DATE,
                    0,
                    member.size,
                    member.size,
                    len(name),
                    0,
                )
                + name
            )
            crc, digest, count = 0, hashlib.sha256(), 0
            with located(dataset, member.path).open("rb") as source:
                while chunk := source.read(read_bytes):
                    crc = zlib.crc32(chunk, crc)
                    digest.update(chunk)
                    count += len(chunk)
                    out.write(chunk)
            if count != member.size or digest.hexdigest() != member.sha256:
                raise ValueError(f"Dataset file changed while zipping: {member.path}")
            end = out.tell()
            out.seek(offset + 14)
            out.write(struct.pack("<I", crc))
            out.seek(end)
            central += struct.pack(
                "<IHHHHHHIIIHHHHHII",
                CENTRAL,
                MADE_BY,
                VERSION,
                flags,
                0,
                DOS_TIME,
                DOS_DATE,
                crc,
                member.size,
                member.size,
                len(name),
                0,
                0,
                0,
                0,
                REGULAR_FILE,
                offset,
            )
            central += name
        start = out.tell()
        out.write(central)
        count = len(item.members)
        out.write(
            struct.pack("<IHHHHIIH", END, 0, 0, count, count, len(central), start, 0)
        )


def verify(path: Path, item: TableZip) -> str:
    """The clients' reader lists exactly the planned members; returns the zip digest."""
    if path.stat().st_size != item.size:
        raise ValueError(f"Dataset zip has an unexpected size: {item.name}")
    try:
        summary = transport().inspect_zip(str(path))
    except Exception as error:
        raise ValueError(f"Dataset zip refused by the reader: {item.name}") from error
    found = [(row["path"], row["size"], row["sha256"]) for row in summary["files"]]
    if found != [(m.path, m.size, m.sha256) for m in item.members]:
        raise ValueError(f"Dataset zip differs from its table: {item.name}")
    return sha256_file(path)
