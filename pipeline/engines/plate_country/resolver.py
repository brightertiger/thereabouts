"""Small deterministic reference: rank evidence, preserve ambiguity, never certify."""

import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pipeline.engines.artifacts import read_json
from pipeline.runtime.jsonio import sha256_file
from pipeline.runtime.paths import located

from .geography import Geography, captures
from .policy import Row, normalize, scripts


class Resolver:
    def __init__(self, bundle: Row) -> None:
        self.bundle = bundle
        self.policy = bundle["policy"]
        self.formats = bundle["formats"]
        self.countries = {r["country_code"]: r for r in bundle["countries"]}
        self.priors = {r["country_code"]: r for r in bundle["priors"]}
        self.default_prior = statistics.median(r["vehicles"] for r in bundle["priors"])
        self.geography = Geography(bundle["codes"], self.policy)
        by_script: dict[str, set[str]] = defaultdict(set)
        for rule in self.formats:
            for script in rule["scripts"]:
                by_script[script].add(rule["country_code"])
        self.script_counts = Counter(
            {s: len(countries) for s, countries in by_script.items()}
        )

    @classmethod
    def load(cls, root: Path, manifest_path: Path) -> "Resolver":
        manifest = read_json(manifest_path)
        for item in [*manifest["tables"], manifest["bundle"], manifest["coverage"]]:
            path = located(root, item["path"])
            if (
                path.stat().st_size != item["size"]
                or sha256_file(path) != item["sha256"]
            ):
                raise ValueError(f"Corrupt resolver artifact: {item['path']}")
        return cls(read_json(located(root, manifest["bundle"]["path"])))

    def resolve(
        self, plate: str, country: str | None = None, *, series: str | None = None
    ) -> Row:
        value = normalize(plate)
        if country is not None:
            country = country.upper()
            if country not in self.countries:
                raise ValueError(f"Unknown country/territory: {country}")
        if not value or len(value) > self.policy["max_input_length"]:
            return dict(
                input=plate,
                normalized=value,
                country_code=country,
                level="country" if country else None,
                reason="empty_or_too_long_input",
                candidates=[],
            )
        matching = self._matches(value, country, series)
        if country:
            return dict(
                input=plate,
                normalized=value,
                country_source="caller",
                **self.geography.locate(country, matching, series=series),
                matches=matching,
            )
        candidates = []
        for code in sorted({m["country_code"] for m in matching}):
            evidence = sorted(
                (m for m in matching if m["country_code"] == code),
                key=lambda m: (-m["score"], m["series_id"]),
            )
            candidates.append(
                dict(
                    country_code=code,
                    name=self.countries[code]["name"],
                    score=evidence[0]["score"],
                    evidence=evidence,
                )
            )
        candidates.sort(key=lambda r: (-r["score"], r["country_code"]))
        # An incomplete worldwide catalog cannot certify a singleton as globally unique.
        return dict(
            input=plate,
            normalized=value,
            country_code=None,
            status="ranked_candidates" if candidates else "no_match",
            candidate_count=len(candidates),
            unique_in_catalog=len(candidates) == 1,
            certain=False,
            reason="open_world_catalog_and_special_series",
            candidates=candidates,
        )

    def _matches(
        self, value: str, country: str | None, series: str | None
    ) -> list[Row]:
        result = []
        observed = scripts(value, self.policy["script_patterns"])
        seen = set()
        for rule in self.formats:
            code = rule["country_code"]
            if (country and country != code) or (
                series and series != rule["series_id"]
            ):
                continue
            exact = re.fullmatch(rule["pattern"], value) is not None
            pattern = rule["pattern"] if exact else rule["relaxed_pattern"]
            if not exact and re.fullmatch(pattern, value) is None:
                continue
            captured = captures(pattern, value, rule.get("code_group"))
            known = self.geography.known(code, captured) if captured else []
            key = (code, rule["series_status"], pattern, captured)
            if key in seen:
                continue
            seen.add(key)
            stock = self.priors.get(code)
            weight = self.policy["weights"]
            non_latin = [s for s in observed if s not in ("Latin", "ASCII digits")]
            rarity = max(
                (
                    math.log2(len(self.countries) / max(1, self.script_counts[s]))
                    for s in non_latin
                ),
                default=0.0,
            )
            marks = [mark for mark in rule["fixed_national_marks"] if mark in value]
            components = dict(
                known_code=weight["known_code"] * bool(known),
                fixed_mark=weight["fixed_mark"] * bool(marks),
                script=weight["script"] * rarity,
                specificity=weight["specificity"] * rule["specificity_bits"],
                log_vehicle_prior=weight["log_vehicle_prior"]
                * math.log2(max(1, stock["vehicles"] if stock else self.default_prior)),
                relaxed_penalty=0 if exact else -weight["relaxed_penalty"],
            )
            result.append(
                dict(
                    country_code=code,
                    series_id=rule["series_id"],
                    series_status=rule["series_status"],
                    code=captured,
                    known_code=bool(known),
                    code_sources=sorted({r["source_url"] for r in known}),
                    scripts=observed,
                    fixed_national_marks=marks,
                    match="exact" if exact else "separator_relaxed",
                    pattern=rule["pattern"],
                    score=round(sum(components.values()), 6),
                    score_components=components,
                    prior=stock
                    or dict(
                        vehicles=self.default_prior,
                        imputed=True,
                        reason="missing_country_stock_use_median",
                    ),
                    provenance=rule["provenance"],
                )
            )
        return result


def resolve(bundle: dict[str, Any], plate: str, country: str | None = None) -> Row:
    """Convenience entry point; reuse Resolver for multiple lookups."""
    return Resolver(bundle).resolve(plate, country)
