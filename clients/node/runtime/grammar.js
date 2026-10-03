// Host argument tree. docs/CLI.md is normative; output and batch policy are Rust.
import { usage } from "./errors.js";
const globals = {
  "data-dir": [
    "PATH",
    "Select the installed data store (overrides THEREABOUTS_DATA).",
  ],
  format: [
    "FORMAT",
    "Choose table, JSON, NDJSON or CSV output; table on a TTY.",
  ],
  json: [false, "Print one pretty JSON object (a results array for batches)."],
  csv: [false, "Print CSV with input columns followed by result columns."],
  fields: [
    "?",
    "Select comma-separated result paths; omit the value to list paths.",
  ],
  evidence: [false, "Include source and method details; tables omit evidence."],
  quiet: [false, "Suppress optional progress; preserve results and errors."],
  "no-input": [
    false,
    "Disable interactive confirmation; destructive operations need --yes.",
  ],
  strict: [false, "Exit 1 on no match; batch row errors still exit 5."],
};
const trees = {
  reverse: {
    about: "Find geographic context or read CSV/NDJSON points.",
    args: "[FILE|-] | --lat LAT --lon LON",
    options: {
      lat: "LAT",
      lon: "LON",
      "lat-col": "COLUMN",
      "lon-col": "COLUMN",
    },
  },
  h3: { about: "Find the stored ancestor of an H3 cell.", args: "CELL" },
  geocode: {
    about:
      "Finds towns and cities by name. Street addresses are not supported.",
    args: "TEXT",
    options: {
      country: "CC",
      subdivision: "CODE",
      limit: "N",
      prefer: "population",
    },
  },
  postal: {
    about: "Find a postal code in its source country.",
    args: "CODE --country CC",
    options: { country: "CC" },
  },
  airport: {
    about: "Find an airport by IATA/ICAO or an explicit scheme.",
    args: "CODE",
    options: { scheme: "iata|icao|gps|local|ident", country: "CC" },
  },
  locode: {
    about: "Find a five-character country/location code.",
    args: "CODE",
    options: { country: "CC" },
  },
  ip: {
    about: "Find published context for an IPv4 or IPv6 literal.",
    args: "ADDRESS",
  },
  phone: {
    about: "Find an E.164 prefix; country narrows shared calling codes.",
    args: "NUMBER",
    options: { country: "CC" },
  },
  plate: {
    about: "Find registration country and series context.",
    args: "TEXT",
    options: { country: "CC", series: "NAME" },
  },
  info: { about: "Report active pack identities and capabilities.", args: "" },
  mcp: {
    about: "Serve lookup verbs through the optional Python MCP host.",
    args: "",
  },
  data: { about: "Explicitly manage installed data.", args: "COMMAND" },
  "data install": {
    about: "Install selected pack families.",
    args: "PACK…",
    options: { version: "V", from: "URL|DIR", yes: false },
  },
  "data list": {
    about: "List installed or available packs.",
    args: "",
    options: { remote: false },
  },
  "data verify": {
    about: "Check installed sizes and optionally all hashes.",
    args: "",
    options: { full: false },
  },
  "data remove": {
    about: "Remove all versions of a pack family.",
    args: "PACK",
    options: { yes: false },
  },
  "data path": { about: "Print the resolved data directory.", args: "" },
  "data update": {
    about: "Check for a newer supported release.",
    args: "--check",
    options: { check: false },
  },
};
export function help(command = "") {
  const tree = trees[command],
    rows = Object.entries({
      ...globals,
      ...Object.fromEntries(
        Object.entries(tree?.options ?? {}).map(([k, v]) => [k, [v, ""]]),
      ),
    });
  return (
    `${tree?.about ?? "Offline geographic context from explicitly installed data."}\n\nUsage: thereabouts ${command ? command + " " + tree.args : "[OPTIONS] [COMMAND]"} [OPTIONS]\n` +
    (command === "reverse"
      ? "       thereabouts reverse FILE|- [OPTIONS]\n"
      : "") +
    (!command || command === "data"
      ? "\nCommands:\n" +
        Object.entries(trees)
          .filter(([k]) => (command ? k.startsWith("data ") : !k.includes(" ")))
          .map(([k, v]) => `  ${k.replace(/^data /, "")}  ${v.about}\n`)
          .join("")
      : "") +
    "\nOptions:\n" +
    rows
      .map(
        ([k, [v, description]]) =>
          `  --${k}${v ? " " + (v === "?" ? "[FIELDS]" : v) : ""}  ${description}\n`,
      )
      .join("") +
    "  --help  Print command help.\n" +
    (command === "data install" ? "" : "  --version  Print client version.\n")
  );
}
export function parse(argv) {
  const output = { command: "", values: [], options: {} };
  let terminated = false;
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    if (!terminated && token === "--") {
      terminated = true;
      continue;
    }
    if (!terminated && (token === "--help" || token === "-h"))
      return { ...output, help: true };
    if (
      !terminated &&
      (token === "--version" || token === "-V") &&
      output.command !== "data install"
    )
      return { ...output, version: true };
    if (!terminated && token.startsWith("--")) {
      const at = token.indexOf("="),
        name = token.slice(2, at < 0 ? undefined : at),
        given = at < 0 ? undefined : token.slice(at + 1);
      const spec = globals[name]?.[0] ?? trees[output.command]?.options?.[name];
      if (spec === undefined) throw usage(`Unknown option: --${name}`);
      if (Object.hasOwn(output.options, name))
        throw usage(`Repeated option: --${name}`);
      if (spec === false) {
        if (given !== undefined) throw usage(`--${name} takes no value`);
        output.options[name] = true;
      } else if (
        spec === "?" &&
        given === undefined &&
        (argv[i + 1] === undefined || argv[i + 1].startsWith("-"))
      )
        output.options[name] = "";
      else {
        const value = given ?? argv[++i];
        if (
          value === undefined ||
          (value.startsWith("-") && !["lat", "lon"].includes(name))
        )
          throw usage(`--${name} requires a value`);
        output.options[name] = value;
      }
      continue;
    }
    if (!terminated && token.startsWith("-") && token !== "-")
      throw usage(`Unknown option: ${token}`);
    if (!output.command) {
      if (!trees[token] || token.includes(" "))
        throw usage(`Unknown command: ${token}`);
      output.command = token;
    } else if (output.command === "data") {
      if (!trees["data " + token])
        throw usage(`Unknown data command: ${token}`);
      output.command += " " + token;
    } else output.values.push(token);
  }
  validate(output);
  return output;
}
function validate({ command, values, options: o }) {
  if (["format", "json", "csv"].filter((k) => o[k] !== undefined).length > 1)
    throw usage("Conflicting output selectors");
  if (o.format && !["table", "json", "ndjson", "csv"].includes(o.format))
    throw usage("Use --format table|json|ndjson|csv");
  if (o.fields === "") return;
  if (!command) return;
  if (command === "data") throw usage("data requires a command");
  if (command === "reverse") {
    if (
      values.length > 1 ||
      (values.length && (o.lat !== undefined || o.lon !== undefined))
    )
      throw usage("Use reverse --lat LAT --lon LON or reverse FILE|-");
    if (!values.length) {
      if (
        o.lat === undefined ||
        o.lon === undefined ||
        o["lat-col"] !== undefined ||
        o["lon-col"] !== undefined
      )
        throw usage("reverse requires both --lat and --lon, or a FILE");
      for (const k of ["lat", "lon"]) {
        if (
          !o[k].trim() ||
          (!/^[+-]?(?:nan|inf(?:inity)?)$/i.test(o[k]) &&
            Number.isNaN(Number(o[k])))
        )
          throw usage(`Invalid --${k} number`);
      }
    }
  } else if (command === "data install") {
    if (!values.length) throw usage("Name at least one pack to install");
  } else {
    const wanted = [
      "info",
      "mcp",
      "data path",
      "data list",
      "data verify",
      "data update",
    ].includes(command)
      ? 0
      : 1;
    if (values.length !== wanted)
      throw usage(`${command} requires ${wanted} positional argument(s)`);
  }
  if (command === "postal" && o.country === undefined)
    throw usage("postal requires --country CC");
  if (command === "data update" && !o.check)
    throw usage("data update requires --check");
  if (
    o.scheme !== undefined &&
    !["iata", "icao", "gps", "local", "ident"].includes(o.scheme.toLowerCase())
  )
    throw usage("Unknown airport scheme");
  if (o.prefer !== undefined && o.prefer !== "population")
    throw usage("Use --prefer population");
  if (
    o.limit !== undefined &&
    (!/^\d+$/.test(o.limit) || Number(o.limit) < 1 || Number(o.limit) > 100)
  )
    throw usage("geocode --limit must be 1..100");
}
