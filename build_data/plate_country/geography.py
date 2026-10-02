"""Conservative geographic fallback over explicit registration-unit evidence."""

import re
from collections import defaultdict

from .policy import Row, code_key


class Geography:
    def __init__(self, codes: list[Row], policy: Row) -> None:
        self.policy = policy
        self.index: dict[tuple[str, str], list[Row]] = defaultdict(list)
        for row in codes:
            self.index[row["country_code"], code_key(row["code"])].append(row)

    def known(self, country: str, captured: str) -> list[Row]:
        return self.index.get((country, code_key(captured)), [])

    def locate(
        self, country: str, matches: list[Row], *, series: str | None = None
    ) -> Row:
        result: Row = dict(
            country_code=country,
            level="country",
            locations=[],
            reason="no_matching_format",
        )
        if not matches:
            return result
        config = self.policy["geography"]
        if country in config["excluded_countries"]:
            return dict(result, reason="subdivision_series_context_required")
        if config["block_if_non_geographic_format_matches"] and any(
            not m["code"] for m in matches
        ):
            return dict(result, reason="non_geographic_or_ambiguous_series")
        eligible: list[Row] = []
        parents: list[Row] = []
        for match in matches:
            if match["series_status"] == "historic" and series is None:
                continue
            found = self.known(country, match["code"] or "")
            eligible.extend(r for r in found if self._eligible(r, match))
            length = config["state_prefix"].get(country)
            if length:
                parents.extend(
                    r
                    for r in self.known(country, code_key(match["code"] or "")[:length])
                    if self._eligible(r, match)
                    and self.policy["levels"].get(r["unit_kind"]) == "state"
                )
        for level in ("place", "state"):
            locations = [
                r
                for r in eligible + parents
                if self.policy["levels"].get(r["unit_kind"]) == level
            ]
            if locations:
                # Preserve every distinct source assertion, including disagreements.
                keys = set()
                unique = []
                for row in locations:
                    key = (
                        row["code"],
                        row.get("name_en"),
                        row.get("name_local"),
                        row.get("source_url"),
                    )
                    if key not in keys:
                        keys.add(key)
                        unique.append(row)
                return dict(
                    result,
                    level=level,
                    locations=unique,
                    ambiguous=len(
                        {(r.get("name_en"), r.get("name_local")) for r in unique}
                    )
                    > 1,
                    reason="known_registration_code"
                    if level == "place"
                    else "known_state_code_no_finer_verified_unit",
                )
        return dict(result, reason="unknown_code_or_unverified_temporal_scope")

    def _eligible(self, row: Row, match: Row) -> bool:
        config = self.policy["geography"]
        return bool(
            row.get("scope") not in config["excluded_scopes"]
            and not row.get("subdivision_scope")
            and row.get("series_status") == match["series_status"]
            and row.get("unit_kind") in self.policy["levels"]
        )


def captures(pattern: str, value: str, group: str | None) -> str | None:
    match = re.fullmatch(pattern, value)
    return match.group(group) if match is not None and group else None
