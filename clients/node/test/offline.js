import net from "node:net";
import dns from "node:dns";
import { syncBuiltinESMExports } from "node:module";
const blocked = () => {
  throw new Error("Network access is forbidden in client tests");
};
net.Socket.prototype.connect = blocked;
for (const key of ["lookup", "resolve", "resolve4", "resolve6"])
  dns[key] = blocked;
globalThis.fetch = blocked;
syncBuiltinESMExports();
