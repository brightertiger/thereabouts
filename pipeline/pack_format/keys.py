"""Apply explicit, portable key normalization carried by a code pack."""

from typing import Any

from .input_errors import ContextRequiredError, InvalidInputError

FAMILIES = ("reverse", "postal", "airports")
AIRPORT_SCHEMES = ("iata", "icao", "ident", "gps", "local")
ASCII_SPACE = " \t\r\n\v\f"
UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
OPERATIONS = {"strip_ascii", "upper_ascii", "remove_ascii_spaces"}


def normalization(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"default", "countries"}:
        raise ValueError("Invalid key normalization")
    if not isinstance(value["countries"], dict):
        raise ValueError("Invalid country normalization rules")
    for country, operations in [(None, value["default"]), *value["countries"].items()]:
        if country is not None and country_code(country) != country:
            raise ValueError("Noncanonical country in normalization rules")
        if not isinstance(operations, list) or any(
            op not in OPERATIONS for op in operations
        ):
            raise ValueError("Unknown key normalization operation")
        if len(set(operations)) != len(operations):
            raise ValueError("Repeated key normalization operation")


def country_code(value: object) -> str:
    if value is None:
        raise ContextRequiredError("A country is required")
    if not isinstance(value, str):
        raise InvalidInputError("Country must be a two-letter code")
    result = value.strip(ASCII_SPACE).translate(UPPER)
    if len(result) != 2 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in result):
        raise InvalidInputError("Country must be a two-letter code")
    return result


def normalize(value: object, rules: dict[str, Any], country: str | None) -> str:
    if not isinstance(value, str) or "\0" in value:
        raise InvalidInputError(
            "Code must be a string without NUL; preserve leading zeros"
        )
    operations = rules["countries"].get(country, rules["default"])
    for operation in operations:
        if operation == "strip_ascii":
            value = value.strip(ASCII_SPACE)
        elif operation == "upper_ascii":
            value = value.translate(UPPER)
        elif operation == "remove_ascii_spaces":
            value = value.replace(" ", "")
    if not value:
        raise InvalidInputError("Code must not be empty")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise InvalidInputError("Code must be valid Unicode") from exc
    return value


def key(family: str, code: str, country: str | None, scheme: str | None) -> str:
    if family == "postal":
        if country is None:
            raise ContextRequiredError("Postal lookup requires a country")
        return country + "\0" + code
    if scheme is None:
        raise ContextRequiredError("Airport lookup requires an explicit scheme")
    if scheme not in AIRPORT_SCHEMES:
        raise InvalidInputError(
            "Airport scheme must be iata, icao, ident, gps or local"
        )
    if scheme == "local" and country is None:
        raise ContextRequiredError("Local airport codes require a country")
    return scheme + "\0" + (country or "") + "\0" + code


def check_key(value: str, family: str, rules: dict[str, Any]) -> None:
    parts = value.split("\0")
    if family == "postal" and len(parts) == 2:
        country, code = parts
        scheme = None
    elif family == "airports" and len(parts) == 3:
        scheme, country, code = parts
    else:
        raise ValueError("Invalid compound code key")
    scoped = country_code(country) if country else None
    if scoped != (country or None) or normalize(code, rules, scoped) != code:
        raise ValueError("Noncanonical exact code key")
    if key(family, code, scoped, scheme) != value:
        raise ValueError("Invalid code key context")
