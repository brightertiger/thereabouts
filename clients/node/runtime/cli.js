import fs from "node:fs";
import { writeAll } from "./output.js";
import { spawn } from "node:child_process";
import { parse, help } from "./grammar.js";
import { directory, installed } from "./store.js";
import { wasm } from "./wasm.js";
import { Geocoder } from "./geocoder.js";
import { withIo, readLine } from "./host.js";
import { DataNotInstalledError, usage, atPack } from "./errors.js";
const verbs = {
  h3: "fromH3",
  airport: "airport",
  postal: "postal",
  locode: "locode",
  phone: "phone",
  ip: "ip",
  plate: "plate",
  geocode: "geocode",
};
export function systemIo() {
  return {
    stdout: (s) => writeAll(1, s),
    stderr: (s) => writeAll(2, s),
    readLine,
    env: process.env,
    stdinTTY: !!process.stdin.isTTY,
    stdoutTTY: !!process.stdout.isTTY,
  };
}
export async function run(argv, io = systemIo()) {
  try {
    return await execute(parse(argv), io);
  } catch (error) {
    if (error.code === "EPIPE") return 0;
    if (error.code === "ENOSPC") {
      io.stderr("Not enough disk space to finish the operation\n");
      return 2;
    }
    if (error instanceof DataNotInstalledError) {
      io.stderr(
        `${error.family} data is not installed. Install it with:\nthereabouts data install ${error.family}\n`,
      );
      return 3;
    }
    io.stderr(error.message + "\n");
    return error.exitCode ?? 4;
  }
}
async function execute(parsed, io) {
  const { command, values, options: o } = parsed;
  if (parsed.help) {
    io.stdout(help(command));
    return 0;
  }
  if (parsed.version) {
    io.stdout("thereabouts 0.1.0\n");
    return 0;
  }
  const module = await wasm();
  if (o.fields === "") {
    io.stdout(module.fields() + "\n");
    return 0;
  }
  if (!command) {
    io.stderr(help());
    return 2;
  }
  if (
    o.fields !== undefined &&
    o.fields.split(",").some((f) => !module.fields().split("\n").includes(f))
  )
    throw usage("Unknown result field");
  const root = directory(o["data-dir"], io.env),
    format =
      o.format ??
      (o.json ? "json" : o.csv ? "csv" : io.stdoutTTY ? "table" : "ndjson");
  if (command === "mcp") {
    if (io !== undefined && !process.stdin)
      throw usage("MCP requires a process host");
    return new Promise((resolve, reject) => {
      const child = spawn(
        io.env.THEREABOUTS_PYTHON ?? "python3",
        ["-m", "thereabouts.mcp_service.server"],
        { stdio: "inherit", env: { ...io.env, THEREABOUTS_DATA: root } },
      );
      child.once("error", (error) =>
        reject(
          usage(
            `MCP requires the Python host with thereabouts[mcp] installed: ${error.message}`,
          ),
        ),
      );
      child.once("exit", (code) => resolve(code ?? 4));
    });
  }
  if (command === "info" || command.startsWith("data ")) {
    const { manage } = await import("./management.js");
    const value = await manage(command, values, o, root, io);
    if (["table", "csv"].includes(format) && Array.isArray(value.packs)) {
      const rows =
        command === "info"
          ? value.packs.map((p) => ({
              family: p.family,
              data_version: p.data_version,
              format_minor: p.format_minor,
              client_version: "0.1.0",
              attribution: p.attribution,
            }))
          : value.packs;
      if (!rows.length && format === "table") io.stdout("No installed packs\n");
      else withIo(io, () => module.renderRows(JSON.stringify(rows), format));
      return 0;
    }
    return withIo(io, () =>
      module.render(JSON.stringify(value), format, undefined, false),
    );
  }
  const selected =
    {
      reverse: "core",
      h3: "core",
      geocode: "core",
      airport: "airports",
      plate: "plates",
    }[command] ?? command;
  const packs = { [selected]: await installed(root, selected) };
  if (selected !== "core")
    try {
      packs.core = await installed(root, "core");
    } catch (e) {
      if (!(e instanceof DataNotInstalledError)) throw e;
    }
  const geo = await Geocoder.open({ packs });
  try {
    if (command === "reverse" && values.length) {
      const filename = values[0];
      if (filename !== "-")
        try {
          const stat = fs.statSync(filename);
          if (!stat.isFile()) throw new Error("not a regular file");
        } catch (e) {
          throw usage(`Cannot open input file ${filename}: ${e.message}`);
        }
      return withIo(io, () =>
        geo.handle("core").batch(
          JSON.stringify({
            filename,
            lat_col: o["lat-col"] ?? null,
            lon_col: o["lon-col"] ?? null,
            evidence: !!o.evidence,
            strict: !!o.strict,
            fields: o.fields ?? null,
            format,
          }),
          filename === "-" ? undefined : filename,
        ),
      );
    }
    const result =
      command === "reverse"
        ? await geo.reverse({
            lat: Number(o.lat),
            lon: Number(o.lon),
            evidence: !!o.evidence,
          })
        : await geo[verbs[command]](values[0], {
            evidence: !!o.evidence,
            ...Object.fromEntries(
              ["country", "scheme", "subdivision", "series", "prefer"]
                .filter((k) => o[k] !== undefined)
                .map((k) => [k, o[k]]),
            ),
            ...(o.limit === undefined ? {} : { limit: Number(o.limit) }),
          });
    return withIo(io, () =>
      module.render(JSON.stringify(result), format, o.fields, !!o.strict),
    );
  } catch (e) {
    if (
      ["corrupt_pack", "incompatible_data", "pack_not_found"].includes(e.code)
    )
      throw atPack(e, packs[selected], selected);
    throw e;
  } finally {
    await geo.close();
  }
}
