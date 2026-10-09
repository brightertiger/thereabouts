"""Evidence-only administrative code and telephone links, with explicit ambiguity."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import cast

from pipeline.engines.store.catalog import geonames_class
from pipeline.engines.store.codec import Row, key, rows
from pipeline.engines.store.database import connect
from pipeline.engines.store.entities import entities_in_roles, state_codes

from .inputs import Inputs
from .phone import PhoneCountries

ISO_ALTERNATE_NAME = re.compile(
    r"(?P<primary>.+) \[(?P<alternate>.+) (?P<code>[A-Z]{2}-[A-Z0-9]{1,3})\]"
)


def qualified_aliases(row: Row) -> set[str]:
    """Expand only the row's stated administrative type and coded alternate name."""
    if not row["code_system"].startswith("ISO"):
        return set()
    names = {row[field] for field in ("name", "name_ascii") if row.get(field)}
    for name in list(names):
        alternate = ISO_ALTERNATE_NAME.fullmatch(name)
        if alternate and alternate["code"].startswith(row["country_code"] + "-"):
            names.update((alternate["primary"], alternate["alternate"]))
    if kind := row.get("type"):
        names.update(
            candidate
            for name in list(names)
            for candidate in (f"{name} {kind}", f"{kind} {name}")
        )
    return names


class CodeIndex:
    def __init__(self, inputs: Inputs) -> None:
        self.countries: set[str] = set()
        self.codes: dict[str, set[str]] = {}
        self.names: dict[tuple[str, str], set[str]] = {}
        self.geonames: dict[str, set[str]] = {}
        for cc, path in inputs.paths.items():
            db = connect(path, readonly=True, cache_kib=inputs.limits.sqlite_cache_kib)
            try:
                for identity, role, value in entities_in_roles(
                    db, ("country", "state", "district")
                ):
                    e = cast(Row, value)
                    if role == "country":
                        self.countries.add(cc)
                        if e.get("sovereign"):
                            parent = e["sovereign"][0]
                            self.codes.setdefault(f"iso:{parent}-{cc}", set()).add(
                                identity
                            )
                        continue
                    if e.get("code"):
                        self.codes.setdefault("iso:" + e["code"], set()).add(identity)
                    administrative_identity = False
                    # Administrative GeoNames identity only; a district's
                    # settlement-seat link is not an ADM1 crosswalk.
                    if (
                        e.get("geonames_id")
                        and geonames_class(db, e["geonames_id"]) == "A"
                    ):
                        administrative_identity = True
                        self.geonames.setdefault(e["geonames_id"], set()).add(identity)
                    if (
                        role == "district"
                        and e.get("source_subtype") == "locality"
                        and not administrative_identity
                    ):
                        # Retaining an uncertain locality outside city selection
                        # does not prove that it is an ISO administrative unit.
                        continue
                    names = {e.get("name"), e.get("local_name")}
                    for p in e["provenance"]:
                        evidence = p["evidence"]
                        sources = [evidence]
                        if evidence.get("division_provenance"):
                            sources.append(json.loads(evidence["division_provenance"]))
                        for source in sources:
                            source_names = source.get("upstream", {}).get("names") or {}
                            names.add(source_names.get("primary"))
                            names.update(v for _, v in source_names.get("common") or [])
                    for name in names:
                        if key(name):
                            self.names.setdefault((cc, key(name)), set()).add(identity)
                for identity, crosswalk in state_codes(db):
                    code = crosswalk["geonames_admin1"]
                    if code:
                        self.codes.setdefault(f"geonames:{cc}.{code}", set()).add(
                            identity
                        )
            finally:
                db.close()

    def subdivision(self, row: Row) -> tuple[list[str], str]:
        system = "iso" if row["code_system"].startswith("ISO") else "geonames"
        direct = self.codes.get(f"{system}:{row['code']}", set())
        if direct:
            return sorted(direct), "explicit code or administrative crosswalk"
        identity = self.geonames.get(row.get("geoname_id") or "", set())
        if identity:
            return sorted(identity), "GeoNames administrative identity"
        # Exact normalized aliases within one country. Never fuzzily match a
        # subdivision to an arbitrary city or claim a unique ambiguous alias.
        matches = self.alias_matches(
            row["country_code"],
            {row[field] for field in ("name", "name_ascii") if row.get(field)},
        )
        if matches:
            return sorted(matches), "exact country-scoped administrative alias"
        matches = self.alias_matches(row["country_code"], qualified_aliases(row))
        return sorted(matches), "source-qualified administrative alias"

    def alias_matches(self, country: str, names: set[str]) -> set[str]:
        return set().union(
            *(self.names.get((country, key(name)), set()) for name in names)
        )


def linked_rows(
    path: Path,
    kind: str,
    inputs: Inputs,
    countries: set[str],
    codes: dict[str, set[str]],
    *,
    index: CodeIndex | None = None,
    phone: PhoneCountries | None = None,
) -> Iterator[Row]:
    for row in rows(path, inputs.limits.source_batch_rows):
        cc = row.get("country_code", row.get("territory"))
        country_id = f"country:{cc}" if cc in countries else None
        options: list[str] = []
        expected = row.get("country_codes", [cc])
        method = "source country code"
        if kind == "subdivisions":
            if index is not None:
                options, method = index.subdivision(row)
            else:
                system = "iso" if row["code_system"].startswith("ISO") else "geonames"
                options = sorted(codes.get(f"{system}:{row['code']}", set()))
        elif kind == "phone_prefixes":
            if phone is not None:
                expected, method = phone.resolve(row)
            options = [f"country:{c}" for c in expected if c in countries]
        elif country_id:
            options = [country_id]
        pending = any(
            c
            and c not in inputs.countries
            and c != "001"
            and (inputs.expected is None or c in inputs.expected)
            for c in expected
        )
        if kind == "phone_prefixes" and len(options) == 1 and not pending:
            country_id = options[0]
        status = (
            "pending"
            if pending
            else "matched"
            if len(options) == 1
            else "ambiguous"
            if options
            else "unmatched"
        )
        yield {
            **row,
            "country_id": country_id,
            "place_id": options[0] if len(options) == 1 and not pending else None,
            "place_ids": options,
            "link_status": status,
            "link_method": method,
        }
