import { VERSION } from "./version.js";
import { inventory, active } from "./store.js";
import { source, index, select, compareVersions } from "./transport.js";
import { install, remove } from "./install.js";
import { wasm } from "./wasm.js";
import { DataNotInstalledError, usage, atPack } from "./errors.js";
export async function manage(command, values, options, root, io) {
  switch (command) {
    case "data path":
      return { path: root };
    case "data install":
      return {
        installed: await install(
          root,
          source(options.from, io.env),
          values,
          options.version,
        ),
      };
    case "data list":
      if (options.remote) return index(source(undefined, io.env));
      return {
        packs: (await inventory(root, true)).map(({ path, active, info }) => ({
          path,
          active,
          family: info.family,
          data_version: info.data_version,
          format_minor: info.format_minor,
        })),
      };
    case "info": {
      const entries = await inventory(root);
      if (!entries.length) throw new DataNotInstalledError();
      return {
        client_version: VERSION,
        packs: entries.map((entry) => entry.info),
      };
    }
    case "data verify": {
      const entries = await inventory(root, true),
        module = await wasm();
      if (!entries.length) throw new DataNotInstalledError();
      for (const entry of entries)
        try {
          module.packInfo(entry.path, !!options.full);
        } catch (e) {
          throw atPack(e, entry.path, entry.info.family);
        }
      return {
        verified: options.full ? "full" : "inventory",
        packs: entries.length,
      };
    }
    case "data remove":
      if (!options.yes) {
        if (options["no-input"] || !io.stdinTTY)
          throw usage(
            "data remove requires --yes when input is disabled or not a TTY",
          );
        io.stderr(`Remove all installed ${values[0]} packs? [y/N] `);
        if (!["y", "yes"].includes(io.readLine().trim().toLowerCase()))
          throw usage("Removal cancelled");
      }
      await remove(root, values[0]);
      return { removed: values[0] };
    case "data update": {
      const entries = await inventory(root),
        pin = active(root);
      const families = entries.length
        ? entries.map((entry) => entry.info.family)
        : ["core"];
      const [newest] = select(await index(source(undefined, io.env)), families);
      const current =
        pin?.data_version ?? entries[0]?.info.data_version ?? null;
      return {
        active_version: current,
        available_version: newest,
        update_available:
          current === null || compareVersions(newest, current) > 0,
      };
    }
    default:
      throw usage("Unknown management command");
  }
}
