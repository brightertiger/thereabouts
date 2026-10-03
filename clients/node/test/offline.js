import net from "node:net";
import dns from "node:dns";
import { syncBuiltinESMExports } from "node:module";
const allowed = (host) =>
  ["127.0.0.1", "::1", "[::1]", "localhost"].includes(host);
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  let first = args[0];
  if (Array.isArray(first)) first = first[0];
  const host =
    typeof first === "object"
      ? first.host
      : typeof args[1] === "string"
        ? args[1]
        : "localhost";
  if (!allowed(host ?? "localhost"))
    throw new Error(`Non-loopback network forbidden: ${host}`);
  return connect.apply(this, args);
};
const lookup = dns.lookup;
dns.lookup = function (host, ...args) {
  if (!allowed(host)) throw new Error(`DNS forbidden: ${host}`);
  return lookup.call(this, host, ...args);
};
const fetch = globalThis.fetch;
globalThis.fetch = (url, options) => {
  if (!allowed(new URL(url).hostname))
    throw new Error("Non-loopback fetch forbidden");
  return fetch(url, options);
};
for (const key of [
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "ALL_PROXY",
  "http_proxy",
  "https_proxy",
  "all_proxy",
])
  delete process.env[key];
process.env.NO_PROXY = "*";
syncBuiltinESMExports();
