"""Fixed historical paths recognized by migration, never new output locations.

These names describe the on-disk legacy format, so they intentionally do not
follow configurable paths for future builds.
"""

NORMALIZED = "normalized"
OFFLOADED = "work/offloaded"
PILOT = "work/v2-pilot"
ACTIVE_MANIFEST = "golden/manifest.json"
