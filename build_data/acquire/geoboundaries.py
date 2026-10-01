"""geoBoundaries agent: acquire only explicitly selected, commit-pinned gbOpen layers.

Start with GBR ADM1; preserve original licences/notices, boundary year, update and
build dates independently in provenance. Produce areas with source shape IDs,
levels and ISO mappings; do not assert English for shapeName. Audit rejected
geometry/licences; no global clone/CGAZ acquisition. Follow DATA_PIPELINE.md.
"""

from .workspace import Workspace


def download(workspace: Workspace) -> None:
    """Acquire allowlisted gbOpen layers under workspace.raw('geoboundaries')."""
    raise NotImplementedError("geoboundaries.download awaits its source agent")


def normalize(workspace: Workspace) -> None:
    """Publish selected areas and a verified manifest with per-unit checkpoints."""
    raise NotImplementedError("geoboundaries.normalize awaits its source agent")
