"""Build normalization checkpoints: python -m build_data.cities --countries IN BD."""

import argparse
from pathlib import Path

from build_data.acquire import Workspace
from build_data.acquire.io import fingerprint, write_json
from build_data.acquire.manifests import load_manifest
from build_data.acquire.runtime import single_run
from build_data.golden.inputs import discover

from .build import build_country
from .common import POLICY, builder, policy
from .engine import Engine
from .mapping import export
from .urban import Urban


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--countries", nargs="+")
    parser.add_argument("--policy", type=Path, default=POLICY)
    parser.add_argument("--skip-map", action="store_true")
    args = parser.parse_args()
    workspace = Workspace(args.data_dir.resolve())
    settings = policy(args.policy)
    with single_run(workspace, "cities"):
        implementation = builder()
        inputs = discover(workspace)
        ghsl = load_manifest(workspace, "ghsl")
        urban = Urban(ghsl["partitions"])
        reports = {}
        for cc in args.countries or sorted(inputs.countries):
            report = build_country(
                workspace, cc, inputs.countries[cc], urban, ghsl, settings
            )
            if not args.skip_map:
                engine = Engine(
                    Path(report["index"]["path"]), inputs.paths[cc], urban, settings
                )
                report["mapping"] = export(workspace, report, engine)
            reports[cc] = report
        if builder() != implementation:
            raise ValueError("Normalization code changed during this run; rerun")
        manifest = {
            "completed": True,
            "builder": builder(),
            "policy": settings,
            "inputs": inputs.identity,
            "ghsl": ghsl,
            "countries": reports,
        }
        path = workspace.root / "city_normalized/manifest.json"
        write_json(path, manifest)
        from build_data.acquire import Ledger

        Ledger(workspace.ledger_path).complete(
            "cities.manifest", "current", fingerprint(manifest), [path]
        )


if __name__ == "__main__":
    main()
