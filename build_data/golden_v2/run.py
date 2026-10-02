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
from build_data.golden.inputs import discover, verify_record
from build_data.reconcile.common import Row

from .blocks import build
from .gates import reviewed
from .tables import lookups, places


def implementation() -> str:
    return fingerprint(
        {
            str(p): sha256_file(p)
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
        base = read_json(workspace.root / "golden/manifest.json")
        if not base["completed"] or base["schema_version"] != "golden-1":
            raise ValueError("World normalization requires complete golden-1 base")
        for table in base["tables"]:
            verify_record(table)
        ghsl = load_manifest(workspace, "ghsl")
        reviewed(gate, settings, inputs, base, ghsl)
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
        write_json(output / "normalization.json", normalized)
        identity = fingerprint(
            {"normalization": normalized, "implementation": implementation()}
        )
        cache_path = workspace.work / "v2-base-block-countries.json"
        if cache_path.exists() and read_json(cache_path).get("base") == fingerprint(
            base
        ):
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
            write_json(cache_path, {"base": fingerprint(base), "blocks": dependencies})
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
        write_json(
            output / "manifest.json",
            {
                "schema_version": "golden-2",
                "completed": False,
                "tables": tables,
                "normalization": normalized,
                "base": fingerprint(base),
                "base_manifest": str(
                    (workspace.root / "golden/manifest.json").resolve()
                ),
                "reference_resolution": 8,
                "block_resolution": 3,
                "builder": identity,
            },
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
            "World cells, places and joins finished; run golden_v2 verify before use.",
            flush=True,
        )
