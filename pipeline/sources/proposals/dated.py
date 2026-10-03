"""Resolve mutable dump dates from publisher Last-Modified evidence."""

from datetime import UTC
from email.utils import parsedate_to_datetime

from pipeline.config.sources import SourceSettings
from pipeline.pins.models import SourcePin

from .catalog import load
from .http import Client
from .resolve import files, finish, variables


def propose(settings: SourceSettings) -> SourcePin:
    client = Client(settings)
    catalog = load(settings)
    payloads = files(client, catalog, variables(client, catalog))
    selected = [
        item for item in payloads if item.name == catalog.settings["release_file"]
    ]
    if len(selected) != 1 or not selected[0].last_modified:
        raise ValueError(
            "Dump proposal requires publisher Last-Modified on its release file"
        )
    date = parsedate_to_datetime(selected[0].last_modified)
    if date.tzinfo is None:
        raise ValueError("Publisher dump date has no timezone")
    date = date.astimezone(UTC)
    release = date.strftime(str(catalog.settings["date_format"]))
    return finish(payloads, release, {"dump_date": date.date().isoformat()})
