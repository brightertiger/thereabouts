"""Legacy meaning and original golden rows provide independent expectations."""

from tests.conformance.core_legacy import check
from tools.check_sample_source import check as check_source


def test_legacy_reverse_mapping() -> None:
    assert check() == {
        "matched": 19,
        "unassigned": 1,
        "ineligible": 4,
        "outside_coverage": 2,
        "invalid_input": 8,
        "coarse_cell_intended_change": 1,
    }


def test_independent_golden_cells_extract() -> None:
    result = check_source()
    assert result["checked_r8_requests"] == 131
