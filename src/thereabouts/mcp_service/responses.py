"""Delegate lookup and page its detached results without changing selection."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from mcp.server.mcpserver.exceptions import ToolError

from ..client import Geocoder
from ..client_results import Resolution, plain
from ..errors import GeocoderError
from .models import Airport, Batch, Cell, Coordinates, Page, Postal, Result


@contextmanager
def tool_errors() -> Iterator[None]:
    try:
        yield
    except GeocoderError as exc:
        raise ToolError(f"{type(exc).__name__}: {exc}") from exc
    except OSError as exc:
        raise ToolError("Installed pack I/O failed; verify the selected data") from exc


def lookup(geo: Geocoder, request: Coordinates | Cell | Postal | Airport) -> Resolution:
    if isinstance(request, Coordinates):
        return geo.reverse(request.latitude, request.longitude)
    if isinstance(request, Cell):
        return geo.from_h3(request.cell)
    if isinstance(request, Postal):
        return geo.postal(request.value, country=request.country)
    return geo.airport(request.value, country=request.country, scheme=request.scheme)


def page(answer: Resolution, offset: int, limit: int) -> Page:
    # Serialize only this page's candidates; a large ambiguous answer need not
    # be copied wholesale just to discard most of its observations afterward.
    total = len(answer.candidates)
    stop = min(offset + limit, total)
    result: Result = {
        "status": answer.status,
        "selected": plain(answer.selected),
        "candidates": [plain(item) for item in answer.candidates[offset:stop]],
        "query": plain(answer.query),
        "reference": plain(answer.reference),
        "data": plain(answer.data),
        "warnings": plain(answer.warnings),
        "error": plain(answer.error),
    }
    return Page(
        result=result,
        total_candidates=total,
        offset=offset,
        limit=limit,
        next_offset=stop if stop < total else None,
        truncated=max(0, stop - offset) < total,
    )


def batch_page(
    answers: Iterator[Resolution], total: int, offset: int, limit: int
) -> Batch:
    stop = min(offset + limit, total)
    results = []
    for index, answer in enumerate(answers):
        # Consume all inputs so errors="raise" has the same meaning on every page.
        if offset <= index < stop:
            results.append(cast(Result, answer.to_dict()))
    return Batch(
        results=results,
        count=len(results),
        total_results=total,
        offset=offset,
        limit=limit,
        next_offset=stop if stop < total else None,
        truncated=len(results) < total,
    )
