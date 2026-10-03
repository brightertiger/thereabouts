"""Generate a reviewable AWS Open Data Registry entry without contacting AWS."""

from urllib.parse import urlparse

import yaml

from pipeline.config.release import ReleaseSettings


def entry(settings: ReleaseSettings, destination: str) -> str:
    parsed = urlparse(destination)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError("Registry resources require an owner-configured s3:// bucket")
    prefix = parsed.path.strip("/")
    resource = parsed.netloc + ("/" + prefix if prefix else "")
    value = {
        "Name": settings.title,
        "Description": settings.description,
        "Documentation": settings.documentation,
        "Contact": settings.contact,
        "ManagedBy": settings.contact,
        "UpdateFrequency": settings.update_frequency,
        "Tags": ["geospatial", "mapping", "parquet"],
        "License": "https://opendatacommons.org/licenses/odbl/1-0/",
        "Citation": settings.citation,
        "Resources": [
            {
                "Description": "Versioned Parquet datasets and client packs",
                "ARN": f"arn:aws:s3:::{resource}",
                "Region": settings.region,
                "Type": "S3 Bucket",
            }
        ],
        "DataAtWork": {
            "Tutorials": [
                {
                    "Title": "Read Thereabouts Parquet with DuckDB, PyArrow and pandas",
                    "URL": settings.documentation,
                    "AuthorName": settings.contact,
                }
            ]
        },
    }
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
