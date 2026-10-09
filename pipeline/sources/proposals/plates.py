"""Propose the explicitly reviewed plate evidence URLs, preserving per-file licences.

Both plate sources use it over their own reviewed inventory. Entries marked
`base` are pinned by the registration source and are not pinned again.
"""

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin
from pipeline.sources.policy import read_policies

from .http import Client
from .resolve import finish


def propose(settings: SourceSettings) -> SourcePin:
    client = Client(settings)
    evidence = read_policies(settings)["sources"]
    ignored = {
        "url",
        "download_url",
        "size",
        "sha256",
        "etag",
        "last_modified",
        "retrieved_at",
        "range_verified",
    }
    files = [
        client.pin(
            name,
            spec.get("download_url", spec["url"]),
            {
                "key": name,
                **{key: value for key, value in spec.items() if key not in ignored},
            },
        )
        for name, spec in sorted(evidence.items())
        if not spec.get("base")
    ]
    return finish(files)
