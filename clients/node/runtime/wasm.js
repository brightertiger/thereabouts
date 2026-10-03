import { readFileSync } from "node:fs";
let loaded;
export async function wasm() {
  loaded ??= import("../pkg/thereabouts.js").then((module) => {
    module.initSync({
      module: readFileSync(
        new URL("../pkg/thereabouts_bg.wasm", import.meta.url),
      ),
    });
    return module;
  });
  return loaded;
}
