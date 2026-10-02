"""Project stored labels into evidence-bearing results, without geographic policy."""

from h3.api import basic_int as h3

from ..packs.layout import (
    CITY_METHOD_MASK,
    CITY_METHODS,
    COUNTRY_AREA,
    OFFSHORE,
    STATE_AREA,
)
from ..packs.spatial import Label
from ..results import (
    Candidate,
    Confidence,
    Data,
    Distance,
    Evidence,
    Methods,
    Place,
    Query,
    Reference,
    Resolution,
    Source,
    Warning,
    freeze,
)
from .backend import StoredCell
from .pack import Pack

BASIS = {
    "city_polygon": "source_boundary",
    "rural_polygon": "source_boundary",
    "policy_polygon": "policy_boundary",
    "urban_allocation": "inferred_urban",
    "town_radius": "inferred_extent",
    "rural_nearest": "nearest_settlement",
    "rural_nearest_distant": "nearest_settlement",
}


def data_identity(pack: Pack) -> Data:
    value = pack.manifest
    return Data(
        family=value["family"],
        version=value["data_version"],
        catalogue_epoch=value["catalogue_epoch"],
        manifest_sha256=value["manifest_sha256"],
        golden_sha256=value["golden_sha256"],
        policy_sha256=value["policy_sha256"],
        h3_version=value["h3_version"],
        sources=tuple(Source(**source) for source in value["sources"]),
    )


def place(pack: Pack, reference: int) -> Place | None:
    if not reference:
        return None
    row = pack.record(reference)
    evidence = row["evidence"]
    return Place(
        id=row["place_id"],
        name=row["name"],
        name_en=row["name_en"],
        local_name=row["local_name"],
        role=row["role"],
        settlement_kind=row["settlement_kind"],
        country_code=row["country_code"],
        code=row["code"],
        code_status=row["code_status"],
        code_system=None,
        country_id=pack.identity(row["country_id"]),
        parent_id=pack.identity(row["parent_id"]),
        sovereign_id=pack.identity(row["sovereign_id"]),
        normalized_city_id=pack.identity(row["normalized_city_id"]),
        parent_method=row["parent_method"],
        normalization_method=row["normalization_method"],
        evidence=Evidence(
            evidence["golden_table"],
            freeze(evidence["source_ids"]),
            freeze(evidence["name_provenance"]),
        ),
    )


def candidate(pack: Pack, label: Label) -> Candidate | None:
    country_ref, state_ref, city_ref, flags = label
    if not any(label[:3]):
        return None
    country = place(pack, country_ref)
    state, city = place(pack, state_ref), place(pack, city_ref)
    sovereign = None
    if country_ref:
        sovereign = place(pack, pack.record(country_ref)["sovereign_id"])
    method = CITY_METHODS[flags & CITY_METHOD_MASK]
    basis = BASIS.get(
        method or "", "source_boundary" if country or state else "unknown"
    )
    distance = None
    if method in ("rural_nearest", "rural_nearest_distant"):
        nearest = pack.manifest["nearest"]
        distant = method == "rural_nearest_distant"
        distance = Distance(
            nearest["distant_over_m"] if distant else None,
            nearest["cutoff_m"] if distant else nearest["distant_over_m"],
            nearest["cutoff_m"],
        )
    identity = city or state or country
    assert identity is not None
    return Candidate(
        id=identity.id,
        place=None,
        city=city,
        state=state,
        country=country,
        sovereign=sovereign,
        relationship="spatial_context",
        methods=Methods(
            city=method,
            state="area" if flags & STATE_AREA else None,
            country="area" if flags & COUNTRY_AREA else None,
            land="offshore" if flags & OFFSHORE else "land",
        ),
        confidence=Confidence(basis),
        distance=distance,
    )


def resolution(
    pack: Pack,
    data: Data,
    query: Query,
    cell: int,
    block: int,
    covered: bool,
    found: tuple[int, Label] | None,
    stored_cell: StoredCell,
) -> Resolution:
    stored = stored_cell(block, found[0]) if found is not None else None
    reference = Reference(
        h3=f"{cell:x}",
        resolution=8,
        stored_h3=f"{stored:x}" if stored is not None else None,
        stored_resolution=int(h3.get_resolution(stored))
        if stored is not None
        else None,
    )
    selected = candidate(pack, found[1]) if found is not None else None
    warnings = []
    if selected is not None:
        method = selected.methods.city
        if method == "rural_nearest_distant":
            warnings.append(Warning("distant_nearest"))
        if method in ("urban_allocation", "town_radius"):
            warnings.append(Warning("inferred_extent"))
    return Resolution(
        status=(
            "outside_coverage"
            if not covered
            else "ineligible"
            if found is None
            else "unassigned"
            if selected is None
            else "matched"
        ),
        selected=selected,
        candidates=() if selected is None else (selected,),
        query=query,
        reference=reference,
        data=data,
        warnings=tuple(warnings),
    )
