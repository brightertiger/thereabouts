"""Transport schemas and explicit page limits, separate from the lookup contract."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictStr
from typing_extensions import TypedDict

from ..results import Status


class Result(TypedDict):
    """The core owns nested place schemas; the adapter checks envelope fields."""

    status: Status
    selected: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    query: dict[str, Any]
    reference: dict[str, Any] | None
    data: dict[str, Any]
    warnings: list[dict[str, Any]]
    error: dict[str, Any] | None


MAX_BATCH_POINTS = 1000
# The largest fixture candidate is 4,825 compact UTF-8 bytes. Twenty candidates
# fit about 100 KiB on that sample; the cap is a page count, not a byte guarantee.
PAGE_SIZE = 20
Limit = Annotated[int, Field(strict=True, ge=1, le=PAGE_SIZE)]
Offset = Annotated[int, Field(strict=True, ge=0)]
Points = Annotated[
    list[tuple[StrictFloat, StrictFloat]], Field(max_length=MAX_BATCH_POINTS)
]


class Coordinates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["coordinates"]
    latitude: StrictFloat
    longitude: StrictFloat


class Cell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["h3"]
    cell: StrictStr


class Postal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["postal"]
    value: StrictStr
    country: StrictStr | None = None


class Airport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["airport"]
    value: StrictStr
    country: StrictStr | None = None
    scheme: Literal["iata", "icao", "ident", "gps", "local"] | None = None


Request = Annotated[Coordinates | Cell | Postal | Airport, Field(discriminator="kind")]


class Page(BaseModel):
    """Only candidates are paged; status and selected retain full-answer semantics."""

    result: Result
    total_candidates: int
    offset: int
    limit: int
    next_offset: int | None
    truncated: bool


class Explanation(BaseModel):
    page: Page
    raw_evidence_installed: Literal[False] = False


class Batch(BaseModel):
    results: list[Result]
    count: int
    total_results: int
    offset: int
    limit: int
    next_offset: int | None
    truncated: bool
