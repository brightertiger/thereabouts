"""Public licence notices grouped by the attribution on pinned input files."""

from collections import defaultdict

from .source import Row


def rows(sources: Row) -> list[Row]:
    result = []
    for name, source in sorted(sources.items()):
        grouped: dict[tuple[str, str], list[Row]] = defaultdict(list)
        for file in source["pin"]["files"]:
            metadata = file["metadata"]
            boundary = metadata.get("metadata", {})
            licence = metadata.get("license") or boundary.get("boundaryLicense")
            attribution = metadata.get("attribution")
            if not attribution and boundary.get("boundarySource"):
                attribution = f"geoBoundaries; {boundary['boundarySource']}"
            licence = licence or source["id"]
            attribution = attribution or source["attribution"]
            if licence in {"per-file", "per-layer", "per-source"}:
                raise ValueError(f"Missing pinned licence: {name}/{file['name']}")
            grouped[(licence, attribution)].append(file)
        for (licence, attribution), files in sorted(grouped.items()):
            result.append(
                {
                    "source": name,
                    "license": licence,
                    "attribution": attribution,
                    "files": sorted(file["name"] for file in files),
                }
            )
    return result


def table(sources: Row, *, include_files: bool) -> str:
    columns = ["Source", "Licence", "Attribution"]
    if include_files:
        columns.append("Pinned files")
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for row in rows(sources):
        values = [row["source"], row["license"], row["attribution"]]
        if include_files:
            values.append(", ".join(f"`{name}`" for name in row["files"]))
        lines.append(
            "| "
            + " | ".join(
                value.replace("|", r"\|").replace("\n", " ") for value in values
            )
            + " |"
        )
    return "\n".join(lines)
