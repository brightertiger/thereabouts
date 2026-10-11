# Thereabouts over MCP

The MCP server is read-only and offline. It offers the tools `reverse`, `h3`, `geocode`,
`postal`, `airport`, `locode`, `phone`, `ip` and `plate`, plus `describe` for the dataset
tables. No tool installs data, so install the packs first (see `../README.md`).

## Setup

1. Install the Python client with the MCP extra: `python -m pip install "thereabouts[mcp]"`.
   The Node `thereabouts mcp` command hands off to the same Python server, so it needs the
   extra too.
2. Add `client-config.json` to your MCP client (for Claude Desktop, merge its
   `mcpServers` entry into `claude_desktop_config.json`; for Claude Code, run
   `claude mcp add thereabouts -- thereabouts --data-dir /absolute/path/to/store mcp`).
3. Replace `/absolute/path/to/your/store`. To use the default store, drop the
   `--data-dir` pair; `THEREABOUTS_DATA` is honoured as well. Run
   `thereabouts data path` to see which directory that is.
4. Restart the client. The server prints nothing to the protocol stream, so a silent start
   is normal. A start without the extra exits with code 2 and an installation hint.

## Example prompts

Each prompt should make the assistant call the named tool and report the status honestly.

1. "Where is latitude 48.8584, longitude 2.2945? Give me the city, country and time zone,
   and say whether the match is exact." Expect a `reverse` call returning Paris, FR,
   Europe/Paris with match `contained`.
2. "Look up the airport CDG, then the postal code 75001 in France, then the port BEANR. For each,
   tell me the city and country." Expect `airport`, `postal` and `locode` calls. CDG's city is
   Tremblay-en-France, the canonical settlement rather than the postal town.
3. "Which country is the phone number +32 2 555 1234 from, and where is the IP address
   8.8.8.8 located? Also, which country could the plate 05-GJV-1 be from?" Expect `phone`
   (BE), `ip` (US, provider range location) and `plate` (possibly ambiguous; the answer should
   list candidates instead of picking one).
