"""Build a local plate sample; never run a pipeline stage or fetch inputs."""

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa

from thereabouts import _core
from tools.build_forward_samples import ROOT
from tools.forward_sample import COUNTRIES, Subset
from tools.plate_sample_inputs import CODE_FIELDS, load


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
        for kind, rows, schema in [
            (
                "plate_formats",
                [
                    {
                        k: (
                            json.dumps(r[k], ensure_ascii=False, sort_keys=True)
                            if k == "provenance"
                            else r.get(k)
                        )
                        for k in (
                            "country_code",
                            "series_id",
                            "series_status",
                            "pattern",
                            "relaxed_pattern",
                            "code_group",
                            "scripts",
                            "fixed_national_marks",
                            "specificity_bits",
                            "provenance",
                        )
                    }
                    for r in bundle["formats"]
                ],
                pa.schema(
                    [
                        (k, pa.string())
                        for k in (
                            "country_code",
                            "series_id",
                            "series_status",
                            "pattern",
                            "relaxed_pattern",
                            "code_group",
                            "provenance",
                        )
                    ]
                    + [
                        ("scripts", pa.list_(pa.string())),
                        ("fixed_national_marks", pa.list_(pa.string())),
                        ("specificity_bits", pa.float64()),
                    ]
                ),
            ),
            (
                "plate_codes",
                bundle["codes"],
                pa.schema(
                    [
                        (
                            k,
                            pa.list_(pa.string())
                            if k == "subdivision_codes"
                            else pa.string(),
                        )
                        for k in CODE_FIELDS
                    ]
                ),
            ),
            (
                "plate_policy",
                [
                    {
                        "policy_json": json.dumps(
                            bundle["policy"], ensure_ascii=False, sort_keys=True
                        )
                    }
                ],
                pa.schema([("policy_json", pa.string())]),
            ),
        ]:
            source.write(kind, rows, schema)
        if bundle["priors"]:
            prior_fields: list[pa.Field[Any]] = [
                pa.field("country_code", pa.string()),
                pa.field("vehicles", pa.uint64()),
            ]
            source.write("plate_priors", bundle["priors"], pa.schema(prior_fields))
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
        (ROOT / "tests/fixtures/plates-source.json").write_text(
            json.dumps(oracle, ensure_ascii=False, indent=2) + "\n"
        )
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
