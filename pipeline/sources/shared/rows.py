"""Row helpers every adapter shares; each source's historical spelling is an argument.

Normalized bytes must not change when an adapter adopts these, so the
variants (cleaning order, null tokens, JSON separators, key order, ASCII
escaping, NaN) are kept as parameters rather than unified.
"""

import json
import unicodedata
from collections.abc import Callable, Collection, Mapping
from typing import Any, Literal


class RowRejected(ValueError):
    """An unusable source record, kept as rejection evidence; never a failed write."""


def clean_text(
    value: object,
    *,
    order: Literal["nfc_first", "split_first"] = "nfc_first",
    nulls: Collection[str] = (),
) -> str | None:
    """Compose to NFC and collapse whitespace runs into single spaces.

    GeoNames collapses before composing (`split_first`); other sources compose
    first. Non-strings are converted with `str()`. An empty result, or one
    equal to a `nulls` token ignoring case, is None.
    """
    if value is None:
        return None
    text = str(value)
    if order == "split_first":
        result = unicodedata.normalize("NFC", " ".join(text.split()))
    else:
        result = " ".join(unicodedata.normalize("NFC", text).split())
    if not result or result.lower() in nulls:
        return None
    return result


def canonical_json(
    value: object,
    *,
    sort_keys: bool = True,
    separators: tuple[str, str] | None = (",", ":"),
    ensure_ascii: bool = False,
    allow_nan: bool = False,
    default: Callable[[Any], object] | None = None,
) -> str:
    """Sorted, compact, unescaped UTF-8 and finite, as `runtime.jsonio.encode`.

    Sources that published another spelling pass it explicitly; `separators=None`
    is `json`'s spaced default.
    """
    return json.dumps(
        value,
        sort_keys=sort_keys,
        separators=separators,
        ensure_ascii=ensure_ascii,
        allow_nan=allow_nan,
        default=default,
    )


def provenance(
    source_url: object,
    license_url: object,
    attribution: object,
    *details: Mapping[str, object],
) -> dict[str, object]:
    """Licence evidence first, then each mapping of source details in order."""
    result: dict[str, object] = {
        "source_url": source_url,
        "license_url": license_url,
        "attribution": attribution,
    }
    for detail in details:
        result.update(detail)
    return result
