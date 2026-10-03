"""Typed plate adapter tables shared by sample and local rule benchmarks."""

import json
from typing import Any

import pyarrow as pa

from tools.forward_sample import Subset
from tools.plate_sample_inputs import CODE_FIELDS


def write_tables(source: Subset, bundle: dict[str, Any]) -> None:
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
