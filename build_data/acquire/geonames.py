"""GeoNames agent: pin allCountries, alternateNamesV2 and supporting code tables.

Produce current populated places without a population floor, plus names retaining
language, historic/colloquial/preference flags and validity strings. Retain source
admin codes, CC BY notices, modification dates and filtering/rejection counts.
Preserve code maps for reconciliation; follow DATA_PIPELINE.md checkpoint rules.
"""

from .workspace import Workspace


def download(workspace: Workspace) -> None:
    """Acquire pinned dumps and code tables under workspace.raw('geonames')."""
    raise NotImplementedError("geonames.download awaits its source agent")


def normalize(workspace: Workspace) -> None:
    """Publish checkpointed places, names, code maps and a verified manifest."""
    raise NotImplementedError("geonames.normalize awaits its source agent")
