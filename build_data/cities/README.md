# City normalization code and data

`candidates.py` chooses eligible city/town anchors from acquired settlement evidence.
Administrative rank alone does not give a weak village seat absorption authority.
`footprints.py` accepts territorial locality boundaries regardless of the local
city/town/village/hamlet title; either linked GeoNames or Overture anchor can
validate containment, with the primary anchor no more than 250 metres outside.
This tolerance validates evidence; it never enlarges the polygon. Country container exclusions still apply. Non-locality
administrative areas require explicit policy approval. `policy_areas.py` constructs
those approved limits and unions, clipping broad municipalities to their connected
GHSL core where specified. `build.py` stores both original accepted boundaries and
effective boundaries after overlaps are subtracted using the retained source
municipal precedence. This prevents a smaller unlinked part taking a linked
town’s interior.

`boundaries.py` selects accepted municipal limits before broader policy unions.
`allocation.py` divides otherwise unclaimed GHSL cells among unbounded cities and
towns. Bounded cities cannot spread past their limits over an unbounded neighbour.
The nearest one-kilometre core wins locally; elsewhere distance is divided by the
square root of population. Optional rural town radii are disabled in policy.
`engine.py` composes those decisions, repairs invalid broad promotions, retains
rural polygons/nearest villages, marks nearest answers beyond 25 km, and keeps the
50 km limit. `mapping.py` applies the same identity convention to lookup joins.

`policy.json` is production decision data. Country entries provide their reason
and source; footprint entries carry the same metadata. Child `parts`, `independent`,
`identity_aliases` and `excluded_areas` inherit the country's cited convention and
any more specific alias/exclusion evidence. Source IDs refer to the pinned acquired
release, not runtime queries or mutable web pages.

The following files are **test references only**. They never feed candidate
selection, geometry acceptance, allocation, the place map or cell assignment:

- `probes.json`: named fixtures and independently retained metropolitan neighbours.
- `regressions.json`: the 130 failures from the approved plan's prototype, retained
  as a frozen audit list. Runtime production does not read the prototype directory.
- `diagnostic_expectations.json`: frozen expected roll-ups for the GeoNames source
  diagnostic. It predates tuning and cannot be derived from the current city rule.

`quality.py`, `boundary_checks.py`, `regressions.py` and `diagnostic.py` regenerate
metrics. All-boundaries checks census original accepted geometries, including
roll-ups, and count each lost interior cell individually. They do not use the
already-subtracted effective footprints as a substitute for independent ownership.
Review receipts can explain exact observed losses but cannot change assignments.
