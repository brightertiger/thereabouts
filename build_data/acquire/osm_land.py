"""OSM agent: pin split WGS84 land ZIP; produce bounded areas with kind=land.

Preserve islands, holes, poles and seam geometry; audit repairs/rejections and
retain ODbL attribution. Use DATA_PIPELINE.md helpers and per-unit checkpoints.
"""

from .workspace import Workspace


def download(workspace: Workspace) -> None:
    """Acquire pinned OSM land inputs under workspace.raw('osm_land')."""
    raise NotImplementedError("osm_land.download awaits its source agent")


def normalize(workspace: Workspace) -> None:
    """Publish areas partitions and a verified output manifest; skip completed units."""
    raise NotImplementedError("osm_land.normalize awaits its source agent")
