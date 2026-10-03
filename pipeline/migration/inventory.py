"""Read active manifests and locate retained base bytes by their recorded hashes."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from pipeline.runtime.fingerprints import REPOSITORY
from pipeline.runtime.jsonio import Object, digest, read_object, sha256_file
from pipeline.runtime.paths import located, relative
from pipeline.runtime.records import Output, outputs_from_json

from .layout import ACTIVE_MANIFEST, NORMALIZED, OFFLOADED
from .paths import portable


@dataclass
class Inventory:
    root: Path
    imports: dict[str, bytes] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    sources: dict[str, Object] = field(default_factory=dict)
    base: Object = field(default_factory=dict)
    active: Object = field(default_factory=dict)
    base_pointer: Object = field(default_factory=dict)
    active_prefix: str = "golden"
    offloaded: dict[str, Object] = field(default_factory=dict)
    base_outputs: dict[tuple[str, int, str], Output] = field(default_factory=dict)
    base_aliases: dict[str, Output] = field(default_factory=dict)
    base_units: dict[tuple[str, str], Output] = field(default_factory=dict)
    metadata_outputs: dict[tuple[str, int], Output] = field(default_factory=dict)

    @classmethod
    def read(cls, root: Path) -> "Inventory":
        result = cls(root)
        for path in sorted((root / NORMALIZED).glob("*/manifest.json")):
            manifest = read_object(path)
            source = str(manifest["source"])
            if source != path.parent.name or source in result.sources:
                raise ValueError(f"Ambiguous normalized source manifest: {path}")
            result.sources[source] = manifest
            if source == "plates":
                result._plate_evidence(manifest)
            offload = root / OFFLOADED / f"{source}.json"
            if offload.exists():
                state = read_object(offload)
                if state.get("offloaded"):
                    if state.get("source") != source or state.get(
                        "manifest_sha256"
                    ) != digest(manifest):
                        raise ValueError(f"Offload evidence does not bind {source}")
                    result.offloaded[source] = state
        pointer = root / "base_cells/current.json"
        if pointer.exists():
            result.base_pointer = read_object(pointer)
            record = cast(Object, result.base_pointer["manifest"])
            result.base = read_object(located(root, str(record["path"])))
            for table in cast(list[Object], result.base["tables"]):
                output = outputs_from_json([table])[0]
                kind = str(table["kind"])
                result.base_outputs.setdefault(
                    (output.sha256, output.size, kind), output
                )
                if kind in {"cells", "places"}:
                    key = str(table["block" if kind == "cells" else "country"])
                    result.base_units[kind, key] = output
        active = root / ACTIVE_MANIFEST
        if active.exists():
            result.active = read_object(active)
            tables = cast(list[Object], result.active["tables"])
            if not tables or not result.active.get("completed"):
                raise ValueError("Active dataset must be completed before adoption")
            result.active_prefix = str(tables[0]["path"]).split("/")[0]
        # Publication moved the former base metadata beside the active dataset.
        # Locate only small retained metadata here, never walk Parquet trees.
        for path in sorted(root.glob("*/manifest.json")):
            if path.parent.name.startswith("golden"):
                for name in (
                    "manifest.json",
                    "quality.json",
                    "DATA_LICENSES.md",
                    "DATASET_CARD.md",
                ):
                    item = path.parent / name
                    if item.is_file():
                        output = Output(
                            relative(root, item), item.stat().st_size, sha256_file(item)
                        )
                        result.metadata_outputs[(output.sha256, output.size)] = output
        result._base_aliases()
        return result

    def _base_aliases(self) -> None:
        if not self.base:
            return
        tables = {str(t["path"]): t for t in cast(list[Object], self.base["tables"])}
        pointer = cast(Object, self.base_pointer["manifest"])
        parent = Path(str(pointer["path"])).parent
        for record in self.metadata_outputs.values():
            if not record.path.endswith("/manifest.json"):
                continue
            original = read_object(self.root / record.path)
            if digest(original) != self.base.get("source_snapshot"):
                continue
            for table in cast(list[Object], original["tables"]):
                path = (
                    parent / str(table["kind"]) / (digest(table) + ".parquet")
                ).as_posix()
                if path not in tables:
                    raise ValueError("Base snapshot lacks an original table")
                self.base_aliases[str(table["path"])] = outputs_from_json(
                    [tables[path]]
                )[0]

    def output(self, value: Object, *, base: bool = False) -> Output:
        item = cast(Object, portable(value, self.root, self.aliases))
        original = outputs_from_json([item])[0]
        if not base:
            return original
        key = original.sha256, original.size
        if original.path in self.base_aliases:
            output = self.base_aliases[original.path]
            if (output.sha256, output.size) != key:
                raise ValueError(f"Base snapshot hash mismatch: {original.path}")
            return output
        if original.path.startswith("golden/"):
            kind = original.path.split("/")[1]
            if kind in {"cells", "places"}:
                output = self.base_units[kind, Path(original.path).stem]
                if (output.sha256, output.size) != key:
                    raise ValueError(
                        f"Base snapshot disagrees with ledger: {original.path}"
                    )
                return output
            if kind == "lookups":
                kind = original.path.split("/")[2]
            if (*key, kind) in self.base_outputs:
                return self.base_outputs[*key, kind]
            if key in self.metadata_outputs:
                return self.metadata_outputs[key]
            raise ValueError(f"No retained base artifact matches {original.path}")
        return original

    def source_outputs(self, source: str) -> tuple[Output, ...]:
        manifest = self.sources[source]
        records = [manifest["inventory"], *cast(list[Object], manifest["auxiliary"])]
        return tuple(self.output(cast(Object, item)) for item in records)

    def _plate_evidence(self, manifest: Object) -> None:
        """Snapshot six repository JSON inputs; their original bytes stay unchanged."""
        for record in cast(list[Object], manifest["auxiliary"]):
            name = str(record["path"])
            marker = "/build_data/acquire/plates_data/"
            if marker not in name:
                continue
            filename = name.split(marker)[1]
            if "/" in filename or not filename.endswith(".json"):
                raise ValueError("Unexpected repository evidence in plates manifest")
            source = REPOSITORY / "build_data/acquire/plates_data" / filename
            if (
                source.stat().st_size != record["size"]
                or sha256_file(source) != record["sha256"]
            ):
                raise ValueError(
                    f"Repository evidence differs from plates build: {filename}"
                )
            target = f"raw/plates/configuration/{record['sha256']}/{filename}"
            self.imports[target] = source.read_bytes()
            self.aliases[name] = target
