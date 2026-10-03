"""Compute exact resolution-8 centre envelopes for one resolution-3 subtree."""

from h3.api import basic_int as h3

from pipeline.engines.hierarchy import descendants
from pipeline.engines.reconcile.common import Row

from .planning import Dependencies
from .windows import envelopes


def describe(root: int, dependencies: Dependencies, resolution: int) -> Row:
    _, points = descendants(root, resolution)
    bounds = (
        float(points[:, 1].min()),
        float(points[:, 0].min()),
        float(points[:, 1].max()),
        float(points[:, 0].max()),
    )
    countries = sorted(
        {cc for region in envelopes(points) for cc in dependencies.countries(region)}
    )
    return {"root": h3.int_to_str(root), "bounds": bounds, "countries": countries}
