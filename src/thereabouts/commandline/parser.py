"""Command-line vocabulary; output is always JSON or JSON Lines."""

import argparse


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="thereabouts",
        description="Offline place context from installed golden packs",
    )
    selection = root.add_mutually_exclusive_group()
    selection.add_argument("--pack", help="Unpacked, immutable serving directory")
    selection.add_argument(
        "--data-dir", help="Persistent pack store (overrides THEREABOUTS_DATA)"
    )
    commands = root.add_subparsers(dest="command", required=True)
    reverse = commands.add_parser("reverse")
    reverse.add_argument("latitude", type=float)
    reverse.add_argument("longitude", type=float)
    postal = commands.add_parser("postal")
    postal.add_argument("value")
    postal.add_argument("--country", required=True)
    airport = commands.add_parser("airport")
    airport.add_argument("value")
    airport.add_argument(
        "--scheme", choices=("iata", "icao", "ident", "gps", "local"), required=True
    )
    airport.add_argument("--country")
    cell = commands.add_parser("h3")
    cell.add_argument("cell")
    for name in ("resolve", "explain"):
        resolve = commands.add_parser(name)
        resolve.add_argument("kind", choices=("coordinates", "h3", "postal", "airport"))
        resolve.add_argument("--country")
        resolve.add_argument("--scheme")
        resolve.add_argument("values", nargs="+")
    commands.add_parser("info")
    mcp = commands.add_parser("mcp", help="Serve read-only MCP tools over stdio")
    mcp.add_argument(
        "--families",
        nargs="+",
        choices=("reverse", "postal", "airports"),
        help="Installed families selected at startup (default: reverse)",
    )
    batch = commands.add_parser(
        "batch", help="Read stdin; emit one JSON result per row"
    )
    batch.add_argument("--kind", choices=("coordinates", "h3"), default="coordinates")
    batch.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    batch.add_argument("--latitude-column", default="latitude")
    batch.add_argument("--longitude-column", default="longitude")
    batch.add_argument("--h3-column", default="h3")
    batch.add_argument("--errors", choices=("raise", "collect"), default="raise")
    batch.add_argument("--chunk-size", type=int, default=4096)
    data = commands.add_parser("data").add_subparsers(dest="operation", required=True)
    installer = data.add_parser("install")
    installer.add_argument(
        "--from",
        dest="source",
        required=True,
        help="Local directory or immutable HTTPS manifest URL",
    )
    installer.add_argument("--sha256", required=True, help="Trusted manifest SHA256")
    installer.add_argument(
        "--manifest-bytes",
        type=int,
        help="Trusted manifest byte count (required for URL)",
    )
    installer.add_argument("--offline", action="store_true")
    installer.add_argument("--timeout", type=float, default=30.0)
    data.add_parser("list")
    verifier = data.add_parser("verify")
    verifier.add_argument("--family", choices=("reverse", "postal", "airports"))
    verifier.add_argument(
        "--full", action="store_true", help="Verify all payload hashes and structures"
    )
    return root
