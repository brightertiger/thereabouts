"""A verified table inventory with paths scoped to its read-only input root."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from h3.api import basic_int as h3

from pipeline.config.schema import H3
from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import digest, sha256_file
from pipeline.runtime.paths import located, validate_relative
from pipeline.runtime.records import Output

Row = dict[str, Any]
ADVISORY = ("countries", "boundary_losses", "lost_cells", "footprint_failures")
# The scopes of config/policies/quality.yaml, repeated so that packs and publish
# do not hash the policy loaders; a test keeps the two equal.
SCOPES = ("reviewed", "all")


@dataclass(frozen=True)
class TableFile:
    kind: str
    path: str
    size: int
    sha256: str
    rows: int
    country: str = ""
    block: str = ""

    def __post_init__(self) -> None:
        if (
            not all(
                isinstance(v, str)
                for v in (self.kind, self.path, self.sha256, self.country, self.block)
            )
            or type(self.size) is not int
            or type(self.rows) is not int
        ):
            raise ValueError("Input table record types are invalid")
        Output(self.path, self.size, self.sha256)
        for value in (self.kind, self.country):
            if value:
                validate_relative(value)
                if len(Path(value).parts) != 1:
                    raise ValueError(
                        "Table and country labels must be single path components"
                    )
        if not self.kind or self.rows < 0:
            raise ValueError("Input table kind and row count are invalid")


@dataclass
class Snapshot:
    root: Path
    manifest: Row
    manifest_sha256: str
    tables: dict[str, list[TableFile]]

    @classmethod
    def read(cls, root: Path, manifest_path: Path, grid: H3) -> "Snapshot":
        value = read_json(manifest_path)
        if not value.get("completed") or not value.get("tables"):
            raise ValueError("Release requires a completed table manifest")
        if (value.get("reference_resolution"), value.get("block_resolution")) != (
            grid.cell_resolution,
            grid.block_resolution,
        ):
            raise ValueError("Input grid differs from release configuration")
        normalization = value.get("normalization", {})
        if not normalization.get("completed") or not isinstance(
            normalization.get("policy"), dict
        ):
            raise ValueError(
                "Release requires completed city normalization and its policy"
            )
        tables: dict[str, list[TableFile]] = defaultdict(list)
        seen: set[str] = set()
        for record in value["tables"]:
            required = {"kind", "path", "size", "sha256", "rows"}
            if not isinstance(record, dict) or not required <= record.keys():
                raise ValueError("Input table record is incomplete")
            entry = TableFile(
                **{
                    key: record[key]
                    for key in TableFile.__dataclass_fields__
                    if key in record
                }
            )
            if entry.kind == "cells":
                try:
                    block = int(entry.block, 16)
                except ValueError as error:
                    raise ValueError(
                        "Release input cells require block identifiers"
                    ) from error
                if (
                    not h3.is_valid_cell(block)
                    or h3.get_resolution(block) != grid.block_resolution
                ):
                    raise ValueError("Input cell block has the wrong H3 resolution")
            if entry.path in seen:
                raise ValueError(f"Duplicate input table path: {entry.path}")
            if (
                not entry.kind
                or entry.size < 0
                or entry.rows < 0
                or len(entry.sha256) != 64
            ):
                raise ValueError(f"Invalid input table record: {entry.path}")
            seen.add(entry.path)
            tables[entry.kind].append(entry)
        return cls(root, value, sha256_file(manifest_path), dict(tables))

    def path(self, record: TableFile) -> Path:
        return located(self.root, record.path)

    def verify(self, record: TableFile) -> Path:
        path = self.path(record)
        if path.stat().st_size != record.size or sha256_file(path) != record.sha256:
            raise ValueError(f"Release input checksum differs: {record.path}")
        if pq.read_metadata(path).num_rows != record.rows:
            raise ValueError(f"Release input row count differs: {record.path}")
        return path

    @property
    def policy(self) -> Row:
        return dict(self.manifest["normalization"]["policy"])

    @property
    def quality_gates(self) -> Row | None:
        """The lookups gate scope and advisory totals with their quality.json record;
        None for an input written before the gates were scoped."""
        gates = self.manifest.get("quality_gates")
        if gates is None:
            return None
        advisory = gates.get("advisory") if isinstance(gates, dict) else None
        if (
            not isinstance(advisory, dict)
            or gates.get("blocking_scope") not in SCOPES
            or not isinstance(gates.get("reviewed_countries"), list)
            or set(advisory) != set(ADVISORY)
            or any(type(advisory[key]) is not int for key in ADVISORY)
        ):
            raise ValueError("Input quality gates are malformed")
        if "report" in gates:  # A released dataset read back as input.
            return dict(gates)
        reports = [
            record
            for record in self.manifest.get("verification_artifacts") or []
            if Path(record["path"]).name == "quality.json"
        ]
        if len(reports) != 1:
            raise ValueError("Input quality gates need one quality.json record")
        return {**gates, "report": reports[0]}

    @property
    def content_identity(self) -> str:
        # Physical roots are intentionally excluded from reproducible identities.
        return digest({"manifest": self.manifest_sha256, "policy": self.policy})


def external(directory: Path, grid: H3) -> Snapshot:
    """Read an existing golden or release directory without copying its ledger."""
    manifest = directory / "manifest.json"
    metadata = read_json(manifest)
    relative_root = metadata.get("data_root", ".")
    if relative_root not in {".", ".."}:
        raise ValueError("Input data_root must be '.' or '..'")
    root = directory.parent if relative_root == ".." else directory
    return Snapshot.read(root, manifest, grid)
