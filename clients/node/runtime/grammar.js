// The JSON command description, parser and help renderer are owned by cli-core.
import { wasm } from "./wasm.js";
export async function parse(argv) {
  return JSON.parse((await wasm()).parseArgs(JSON.stringify(argv)));
}
export async function help(command = "") {
  return (await wasm()).commandHelp(command);
}
export async function description() {
  return JSON.parse((await wasm()).grammar());
}
