"""Resumable detached world controller; a measured, reviewed pilot is mandatory."""

from collections import Counter, OrderedDict
from pathlib import Path

import pyarrow.parquet as pq

from build_data.acquire import Workspace
from build_data.acquire.artifacts import read_json
from build_data.acquire.io import fingerprint, sha256_file, write_json
from build_data.acquire.manifests import load_manifest
from build_data.acquire.runtime import single_run
from build_data.cities.build import build_country
from build_data.cities.common import builder, policy
from build_data.cities.engine import Engine
from build_data.cities.urban import Urban
from build_data.golden import paths as data_paths
from build_data.golden.inputs import discover, verify_record
from build_data.reconcile.common import Row

from .base import load
from .blocks import build
from .gates import reviewed
from .tables import lookups, places


def implementation() -> str:
    return fingerprint(
        {
            p.relative_to(Path(__file__).parents[2]).as_posix(): sha256_file(p)
            for folder in (
                Path(__file__).parent,
                Path(__file__).parents[1] / "golden",
                Path(__file__).parents[1] / "cities",
            )
            for p in folder.iterdir()
            if p.suffix in {".py", ".json"}
        }
    )


def run(workspace: Workspace, output: Path, gate: Path) -> None:
    settings = policy()
    with single_run(workspace, "golden-v2"):
        output.mkdir(parents=True, exist_ok=True)
        run_path = workspace.work / "v2-run.json"
        write_json(
            run_path,
            {"completed": False, "stage": "verify inputs", "output": str(output)},
        )
        code = implementation()
        normalization_code = builder()
        inputs = discover(workspace)
        base_path, base = load(workspace, inputs)
        ghsl = load_manifest(workspace, "ghsl")
        reviewed(gate, settings, inputs, base, ghsl, root=workspace.root)
        existing = output / "manifest.json"
        if existing.exists():
            previous = data_paths.read(existing, workspace.root)
            if (
                previous.get("completed")
                and previous.get("implementation") == code
                and previous.get("base") == data_paths.digest(base, workspace.root)
            ):
                for artifact in [
                    *previous["tables"],
                    *previous["verification_artifacts"],
                ]:
                    verify_record(artifact)
                write_json(
                    run_path,
                    {"completed": True, "stage": "verified", "output": str(output)},
                )
                print("Verified normalized dataset already complete", flush=True)
                return
        urban = Urban(ghsl["partitions"])
        reports = {}
        for cc in sorted(inputs.countries):
            reports[cc] = build_country(
                workspace, cc, inputs.countries[cc], urban, ghsl, settings
            )
            write_json(
                run_path,
                {
                    "completed": False,
                    "stage": "normalize countries",
                    "countries": len(reports),
                    "last": cc,
                },
            )
        normalized = {
            "completed": True,
            "builder": builder(),
            "policy": settings,
            "inputs": inputs.identity,
            "ghsl": ghsl,
            "countries": reports,
        }
        data_paths.write(output / "normalization.json", normalized, workspace.root)
        identity = data_paths.digest(
            {"normalization": normalized, "implementation": implementation()},
            workspace.root,
        )
        cache_path = workspace.work / "v2-base-block-countries.json"
        if cache_path.exists() and read_json(cache_path).get(
            "base"
        ) == data_paths.digest(base, workspace.root):
            dependencies = read_json(cache_path)["blocks"]
        else:
            dependencies = {}
            for table in base["tables"]:
                if table["kind"] == "cells":
                    column = pq.read_table(table["path"], columns=["country_id"])[
                        "country_id"
                    ]
                    dependencies[table["block"]] = sorted(
                        {
                            v.removeprefix("country:")
                            for v in column.unique().to_pylist()
                            if v
                        }
                    )
            write_json(
                cache_path,
                {
                    "base": data_paths.digest(base, workspace.root),
                    "blocks": dependencies,
                },
            )
        cache: OrderedDict[str, Engine] = OrderedDict()
        cell_tables = []
        country_counts: dict[str, Row] = {}
        blocks = sorted(
            (r for r in base["tables"] if r["kind"] == "cells"),
            key=lambda r: (dependencies[r["block"]], r["block"]),
        )
        for ordinal, record in enumerate(blocks):
            active = {}
            for cc in dependencies[record["block"]]:
                if cc not in cache:
                    cache[cc] = Engine(
                        Path(reports[cc]["index"]["path"]),
                        inputs.paths[cc],
                        urban,
                        settings,
                        (Path(inputs.land["path"]), inputs.policy["offshore_m"]),
                    )
                cache.move_to_end(cc)
                active[cc] = cache[cc]
                while len(cache) > 2:
                    cache.popitem(last=False)
            result = build(
                workspace,
                output,
                record,
                active,
                identity,
                settings["town_radius"]["enabled"],
            )
            cell_tables.append(result["table"])
            for cc, counts in result["countries"].items():
                entry = country_counts.setdefault(
                    cc,
                    {"eligible": 0, "changed_city": 0, "method_transitions": Counter()},
                )
                entry["eligible"] += counts["eligible"]
                entry["changed_city"] += counts["changed_city"]
                entry["method_transitions"].update(counts["method_transitions"])
            if ordinal % 100 == 0 or ordinal + 1 == len(blocks):
                write_json(
                    run_path,
                    {
                        "completed": False,
                        "stage": "cells",
                        "blocks": ordinal + 1,
                        "total_blocks": len(blocks),
                        "last": record["block"],
                    },
                )
                print(f"v2 cells {ordinal + 1}/{len(blocks)}", flush=True)
        cache.clear()
        write_json(output / "transitions.json", country_counts)
        write_json(run_path, {"completed": False, "stage": "places and maps"})
        tables = places(workspace, output, base, normalized, inputs, urban)
        write_json(run_path, {"completed": False, "stage": "lookup joins"})
        tables.extend(lookups(workspace, output, base, cell_tables))
        tables.extend(cell_tables)
        if implementation() != code or builder() != normalization_code:
            raise ValueError("Build code changed during world run; rerun")
        data_paths.write(
            output / "manifest.json",
            {
                "schema_version": "golden-2",
                "data_root": data_paths.relative(workspace.root, output),
                "completed": False,
                "tables": tables,
                "normalization": normalized,
                "base": data_paths.digest(base, workspace.root),
                "base_manifest": str(base_path),
                "reference_resolution": 8,
                "block_resolution": 3,
                "builder": identity,
                "implementation": code,
            },
            workspace.root,
        )
        write_json(
            run_path,
            {
                "completed": False,
                "stage": "awaiting final quality and integrity",
                "output": str(output),
            },
        )
        print(
            "World cells, places and joins finished; "
            "run normalize_cells verify before use.",
            flush=True,
        )
