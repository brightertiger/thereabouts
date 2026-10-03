"""Build a local plate sample; never run a pipeline stage or fetch inputs."""

import argparse
import json
import tempfile
from pathlib import Path

from thereabouts import _core
from tools.build_forward_samples import ROOT
from tools.forward_sample import COUNTRIES, Subset
from tools.plate_dataset import write_tables
from tools.plate_sample_inputs import load
from tools.source_fixture import write_source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--normalized", type=Path)
    args = parser.parse_args()
    normalized = args.normalized or args.golden.parent / "normalized/plates_country"
    bundle, inputs, total, mode = load(args.golden.parent, normalized)
    with tempfile.TemporaryDirectory(dir=ROOT / ".tmp", prefix="plates-") as directory:
        source = Subset(args.golden, Path(directory))
        source.inputs.update(inputs)
        source.context(
            [
                {"country_code": c, "country_id": "country:" + c}
                for c in sorted(COUNTRIES)
            ]
        )
        # Country hints use the complete published country universe, not guessed names.
        source.tables = [t for t in source.tables if t["kind"] != "countries"]
        countries = []
        for table in source.inventory("countries"):
            for batch in source.batches(table):
                countries.extend(batch.to_pylist())
                schema = batch.schema
            source.write("countries", countries, schema)
        write_tables(source, bundle)
        provenance = source.finish("plates", total)
        provenance["input_mode"] = mode
        provenance["subset_policy"] = (
            "all committed format rules for seven countries; first 32 distinct codes "
            "plus named examples; all registration units and "
            "one entity association per code"
        )
        output = ROOT / "tests/fixtures/packs/plates-sample"
        _core.write_pack(
            str(source.output),
            "plates",
            str(output),
            {
                "data_version": "2026.10",
                "input_provenance": provenance,
                "allow_missing_tables": [] if bundle["priors"] else ["plate_priors"],
                "sources": ["plate source tables and committed plate-country policies"],
                "attribution": (
                    "Plate sources retain per-row licenses; "
                    "see golden notices and format provenance"
                ),
                "notices": {
                    name: (args.golden / name).read_text()
                    for name in ("DATA_LICENSES.md", "DATASET_CARD.md")
                },
            },
        )
        oracle = {
            "provenance": provenance,
            "rows": bundle["codes"] + bundle["formats"],
            "bundle": bundle | {"countries": countries},
        }
        write_source(ROOT / "tests/fixtures/plates-source.json.gz", oracle)
        print(
            json.dumps(
                {
                    "family": "plates",
                    "sample_rows": len(oracle["rows"]),
                    "world_source_rows": total,
                    "bytes": sum(p.stat().st_size for p in output.iterdir()),
                    "input_mode": mode,
                }
            )
        )


if __name__ == "__main__":
    main()
