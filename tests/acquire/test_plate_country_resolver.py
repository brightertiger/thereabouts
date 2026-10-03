"""Reference behavior over invented countries and codes; no external data/network."""

from copy import deepcopy
from pathlib import Path

import pytest

from pipeline.engines.plate_country.policy import Row, code_key, normalize, policy
from pipeline.engines.plate_country.resolver import Resolver
from pipeline.engines.plate_country.syntax import relaxed_pattern, specificity
from pipeline.engines.storage import file_record
from pipeline.runtime.jsonio import write_json


def rule(country: str, pattern: str, **extra: object) -> Row:
    return dict(
        country_code=country,
        series_id="ordinary",
        series_status="current",
        pattern=pattern,
        relaxed_pattern=relaxed_pattern(pattern),
        code_group="code" if "?P<code>" in pattern else None,
        specificity_bits=specificity(pattern),
        scripts=["Latin", "ASCII digits"],
        fixed_national_marks=[],
        provenance={"url": "https://example.invalid/rule"},
        **extra,
    )


def unit(code: str, name: str, kind: str = "district") -> Row:
    return dict(
        country_code="XY",
        code=code,
        name_en=name,
        name_local=None,
        unit_kind=kind,
        scope="registration_unit",
        series_status="current",
        source_url="https://example.invalid/codes",
    )


@pytest.fixture
def bundle() -> Row:
    settings = deepcopy(policy("inference"))
    settings["geography"]["state_prefix"] = {"XY": 2}
    pattern = r"(?P<code>[A-Z]{2}-[0-9]{2}) [A-Z]{2} [0-9]{4}"
    return dict(
        policy=settings,
        countries=[dict(country_code=c, name=c, region="Test") for c in ("XY", "XZ")],
        priors=[
            dict(country_code="XY", vehicles=100_000),
            dict(country_code="XZ", vehicles=10_000_000),
        ],
        formats=[rule(c, pattern) for c in ("XY", "XZ")],
        codes=[unit("AA-12", "North"), unit("AA", "Province", "state")],
    )


def test_code_evidence_can_outweigh_large_prior_without_certainty(bundle: Row) -> None:
    resolver = Resolver(bundle)
    inferred = resolver.resolve("aa-12 ab 3456")
    assert [r["country_code"] for r in inferred["candidates"]] == ["XY", "XZ"]
    assert inferred["country_code"] is None and inferred["certain"] is False
    evidence = inferred["candidates"][0]["evidence"][0]
    assert evidence["known_code"] and evidence["code_sources"]
    unknown = resolver.resolve("ZZ-99 AB 3456")
    assert unknown["candidates"][0]["country_code"] == "XZ"


def test_country_hint_degrades_place_state_country(bundle: Row) -> None:
    resolver = Resolver(bundle)
    assert resolver.resolve("AA-12 AB 3456", "xy")["level"] == "place"
    state = resolver.resolve("AA-99 AB 3456", "XY")
    assert state["level"] == "state"
    assert state["locations"][0]["name_en"] == "Province"
    for text in ("ZZ-99 AB 3456", "MY VANITY", "", "A" * 65):
        result = resolver.resolve(text, "XY")
        assert result["level"] == "country" and result["country_code"] == "XY"
        assert result["reason"]
    with pytest.raises(ValueError, match="Unknown country"):
        resolver.resolve("AA-12 AB 3456", "ZZ")


def test_known_code_is_not_proof_of_an_entity_association(bundle: Row) -> None:
    bundle["codes"] = [dict(unit("AA-12", "Municipality"), scope="entity_association")]
    resolver = Resolver(bundle)
    assert resolver.resolve("AA-12 AB 3456")["candidates"][0]["evidence"][0][
        "known_code"
    ]
    assert resolver.resolve("AA-12 AB 3456", "XY")["level"] == "country"


def test_unknown_time_scope_cannot_become_a_verified_location(bundle: Row) -> None:
    bundle["codes"] = [dict(unit("AA-12", "North"), series_status="unknown")]
    bundle["formats"][0]["series_status"] = "unknown"
    assert Resolver(bundle).resolve("AA-12 AB 3456", "XY")["level"] == "country"


def test_historic_series_requires_context_and_matching_time_scope(bundle: Row) -> None:
    bundle["codes"] = [dict(unit("AA-12", "Old North"), series_status="historic")]
    bundle["formats"][0].update(series_status="historic", series_id="old")
    resolver = Resolver(bundle)
    assert resolver.resolve("AA-12 AB 3456", "XY")["level"] == "country"
    assert resolver.resolve("AA-12 AB 3456", "XY", series="old")["level"] == "place"


def test_non_geographic_overlap_and_subdivision_scopes_abstain(bundle: Row) -> None:
    bundle["formats"].append(rule("XY", r"[A-Z]{2}-[0-9]{2} [A-Z]{2} [0-9]{4}"))
    answer = Resolver(bundle).resolve("AA-12 AB 3456", "XY")
    assert answer["reason"] == "non_geographic_or_ambiguous_series"
    bundle["formats"].pop()
    bundle["codes"] = [dict(unit("AA-12", "County"), subdivision_scope="XY-STATE")]
    assert Resolver(bundle).resolve("AA-12 AB 3456", "XY")["level"] == "country"


def test_disagreements_are_preserved(bundle: Row) -> None:
    bundle["codes"].append(dict(unit("AA-12", "South"), source_url="second-source"))
    answer = Resolver(bundle).resolve("AA-12 AB 3456", "XY")
    assert answer["ambiguous"]
    assert {r["name_en"] for r in answer["locations"]} == {"North", "South"}


def test_separator_relaxation_does_not_insert_alphanumeric_characters(
    bundle: Row,
) -> None:
    resolver = Resolver(bundle)
    matches = resolver.resolve("AA12 AB3456")["candidates"]
    assert matches and matches[0]["evidence"][0]["match"] == "separator_relaxed"
    assert not resolver.resolve("AAX12 AB3456")["candidates"]
    assert resolver.resolve("AA/12·AB.3456")["candidates"]


def test_generic_ties_are_stable_and_duplicate_rules_do_not_add_scores(
    bundle: Row,
) -> None:
    bundle["codes"] = []
    bundle["priors"][1]["vehicles"] = 100_000
    initial = Resolver(bundle).resolve("AA-12 AB 3456")
    bundle["formats"] += [deepcopy(bundle["formats"][1])] * 10
    result = Resolver(bundle).resolve("AA-12 AB 3456")
    assert result == initial
    assert [r["country_code"] for r in result["candidates"]] == ["XY", "XZ"]


def test_native_scripts_do_not_transliterate_and_singleton_is_not_certified(
    bundle: Row,
) -> None:
    bundle["formats"] = [rule("XY", r"京[0-9]{3}")]
    bundle["formats"][0]["scripts"] = ["Han", "ASCII digits"]
    result = Resolver(bundle).resolve("京123")
    assert result["unique_in_catalog"] and not result["certain"]
    assert result["candidates"][0]["evidence"][0]["score_components"]["script"] > 0
    assert normalize("  ab\n\u03b1ß  ") == "AB \u03b1ß"
    assert code_key("粤-B ١۲३") == "粤B123"
    assert code_key("\u041012") != code_key("A12")  # Cyrillic A is not Latin A.


def test_missing_prior_is_explicit_and_bundle_controls_script_policy(
    bundle: Row,
) -> None:
    bundle["priors"].pop()
    bundle["policy"]["script_patterns"] = {"Test alphabet": "[A-Z]"}
    result = Resolver(bundle).resolve("AA-12 AB 3456")
    evidence = next(r for r in result["candidates"] if r["country_code"] == "XZ")[
        "evidence"
    ][0]
    assert evidence["prior"]["imputed"]
    assert evidence["scripts"] == ["Test alphabet"]


def test_artifact_integrity_precedes_loading(tmp_path: Path, bundle: Row) -> None:
    artifact = tmp_path / "bundle.json"
    write_json(artifact, bundle)
    write_json(
        tmp_path / "manifest.json",
        dict(
            bundle=file_record(tmp_path, artifact),
            coverage=file_record(tmp_path, artifact),
            tables=[],
        ),
    )
    Resolver.load(tmp_path, tmp_path / "manifest.json")
    artifact.write_text("{}")
    with pytest.raises(ValueError, match="Corrupt resolver artifact"):
        Resolver.load(tmp_path, tmp_path / "manifest.json")
