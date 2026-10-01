"""Overture agent: pin divisions release 2026-09-23.1, division and division_area.

Produce areas, places (division points including hierarchy parents), and names.
Retain area entity_id=division_id, extent flags, hierarchy/perspectives and nested
sources in provenance; preserve release notices and schema fingerprints. Do not
acquire division_boundary, base/land or Places. Follow DATA_PIPELINE.md.
"""

from .workspace import Workspace


def download(workspace: Workspace) -> None:
    """Acquire pinned division/area objects under workspace.raw('overture')."""
    raise NotImplementedError("overture.download awaits its source agent")


def normalize(workspace: Workspace) -> None:
    """Publish checkpointed areas, places, names and a verified manifest."""
    raise NotImplementedError("overture.normalize awaits its source agent")
