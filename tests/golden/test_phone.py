from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from build_data.golden.code_links import linked_rows
from build_data.golden.inputs import Inputs
from build_data.golden.phone import PhoneCountries


def test_numbering_prefixes_keep_overlap_and_missing_evidence(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "territory": cc,
                    "calling_code": "1",
                    "metadata_xml": (
                        "<territory><fixedLine><nationalNumberPattern>"
                        f"{prefix}[2-9]\\d{{6}}"
                        "</nationalNumberPattern></fixedLine></territory>"
                    ),
                }
                for cc, prefix in [("US", "212"), ("CA", "416")]
            ]
        ),
        metadata,
    )
    phone = PhoneCountries([metadata])
    path = tmp_path / "prefixes.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"prefix": prefix, "country_codes": ["US", "CA"]}
                for prefix in ["1", "1212", "1416", "1999"]
            ]
        ),
        path,
    )
    inputs = Inputs({"US": {}, "CA": {}}, {}, {}, {}, "test", {"US", "CA"})
    result = list(
        linked_rows(path, "phone_prefixes", inputs, {"US", "CA"}, {}, phone=phone)
    )
    assert [r["link_status"] for r in result] == [
        "ambiguous",
        "matched",
        "matched",
        "ambiguous",
    ]
    assert result[1]["place_id"] == "country:US"
    assert result[2]["place_id"] == "country:CA"
    assert result[1]["country_codes"] == ["US", "CA"]
    assert "no numbering-pattern support" in result[3]["link_method"]
    del phone.patterns["CA"]
    assert phone.resolve({"prefix": "1212", "country_codes": ["US", "CA"]})[0] == [
        "US",
        "CA",
    ]
