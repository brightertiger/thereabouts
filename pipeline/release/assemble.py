"""Assemble an immutable dataset in bounded staging, publishing its manifest last."""

import os
import tempfile
from collections import defaultdict
from pathlib import Path

from pipeline.config import Config
from pipeline.content.digest import table_digest
from pipeline.content.sorting import WIDTH
from pipeline.files import file_record
from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import digest, encode, sync_directory
from pipeline.runtime.resources import ResourceGuard

from . import closure, dictionary, keys, metadata, readme, references
from .budget import Budget
from .selection import Selection
from .source import Row, Snapshot
from .tables import assemble_tables, schema_description
from .verify import verify_dataset


def logical_content(
    root: Path, tables: list[Row], config: Config, guard: ResourceGuard
) -> Row:
    grouped: dict[str, list[Row]] = defaultdict(list)
    for table in tables:
        grouped[table["kind"]].append({**table, "path": str(root / table["path"])})
    values = {}
    for kind, records in grouped.items():
        # One live sorted input plus one merge output; scratch is released per table.
        scratch_bytes = 2 * WIDTH * sum(record["rows"] for record in records)
        guard.admit(scratch_bytes)
        try:
            values[kind] = table_digest(records, root / "digest", config.content)
        finally:
            guard.release(scratch_bytes, written_bytes=0)
    content = {"format": "thereabouts-golden-content-1", "tables": values}
    return {**content, "sha256": digest(content)}


def assemble(
    snapshot: Snapshot,
    output: Path,
    config: Config,
    guard: ResourceGuard,
    inputs_hash: str,
    previous: Path | None = None,
) -> list[Path]:
    selection = Selection.from_settings(config.release, config.h3)
    # Refuses, before any work, an input without the lookups quality gates.
    gates = snapshot.quality_gates
    descriptions = schema_description(REPOSITORY / config.release.schema)
    if output.exists():
        saved = verify_dataset(output)
        if saved.get("inputs_hash") != inputs_hash:
            raise ValueError("Release version is immutable; choose a new version")
        return [output / record["path"] for record in saved["files"]] + [
            output / "manifest.json"
        ]
    output.parent.mkdir(parents=True, exist_ok=True)
    budget = Budget(config.release.dataset.max_output_bytes, guard)
    with tempfile.TemporaryDirectory(
        prefix=f".{output.name}-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "dataset"
        staging.mkdir()
        tables, observed, row_licences = assemble_tables(
            snapshot, staging, selection, config.release.dataset, descriptions, budget
        )
        # Missing place keys are aliased, excluded or refused as configured, and
        # a dataset the pack writer would refuse is never published.
        rules = config.release.dataset.closure
        changes = references.plan(staging, tables, descriptions, rules)
        tables = references.apply(
            staging, tables, changes, descriptions, config.release.dataset, budget
        )
        closed = references.record(rules, changes, closure.check(staging, tables))
        keys.check(staging, tables, descriptions, config.content, guard)
        sources = metadata.licences(
            config, observed, metadata.boundary_states(staging, tables)
        )
        stats = metadata.statistics(tables)
        # Assembled tables index the packaging; content.json stays layout-free.
        logical = [t for t in tables if not descriptions[t["kind"]].get("assembled")]
        content = logical_content(staging, logical, config, guard)
        documents = {
            "content.json": encode(content).decode() + "\n",
            "DATA_LICENSES.md": metadata.licence_text(sources, row_licences),
            "DATASET_CARD.md": metadata.card(config, stats, content),
            "CHANGES.md": metadata.changes(config.release.version, content, previous),
            "README.md": readme.render(
                config,
                stats,
                descriptions,
                sources,
                snapshot.policy,
                {"quality_gates": gates, "closure": closed},
                REPOSITORY / config.release.readme_template,
            ),
            # Generated from config/dataset.yaml and the client; the core pack
            # ships the same pair as notices.
            **dictionary.documents(),
        }
        for name, text in documents.items():
            budget.text(staging / name, text)
        files = [*tables, *(file_record(staging, staging / name) for name in documents)]
        manifest = {
            # Wire schema expected by the client writer; not a pipeline identity.
            "schema_version": "golden-2",
            "completed": True,
            "data_root": ".",
            "version": config.release.version,
            "inputs_hash": inputs_hash,
            "reference_resolution": config.h3.cell_resolution,
            "block_resolution": config.h3.block_resolution,
            "normalization": {"completed": True, "policy": snapshot.policy},
            "sources": sources,
            "statistics": stats,
            "schemas": descriptions,
            "selection": {
                "countries": list(selection.countries),
                "blocks": list(selection.blocks),
            },
            "input_manifest_sha256": snapshot.manifest_sha256,
            "logical_sha256": content["sha256"],
            # Lookups gates this export passed; findings outside the blocking
            # scope ship as advisory totals, listed in the quality.json record.
            "quality_gates": gates,
            # Place references rewritten or dropped to close the dataset.
            "closure": closed,
            "tables": tables,
            "files": files,
        }
        budget.text(staging / "manifest.json", encode(manifest).decode() + "\n")
        verify_dataset(staging)
        os.rename(staging, output)
        sync_directory(output.parent)
    return [output / record["path"] for record in files] + [output / "manifest.json"]
