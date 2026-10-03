// Transfer policy is host-owned; lookup modules never import this file.
import fs from "node:fs";
import path from "node:path";
import { EnvHttpProxyAgent } from "undici";
import { safePath } from "./host.js";
import { MAX_METADATA, readJson, component, keys, family } from "./store.js";
import { integrity, usage, ThereaboutsError } from "./errors.js";
export function interrupted(error) {
  if (error instanceof ThereaboutsError || error.exitCode !== undefined)
    return error;
  return usage(
    `Download interrupted; run the same data install again to resume: ${error.message}`,
  );
}
export const DEFAULT_SOURCE = "https://thereabouts-releases.invalid";
export const HEADER_TIMEOUT_MS = 30_000,
  READ_TIMEOUT_MS = 60_000;
export function source(explicit, env = process.env) {
  const value = explicit ?? env.THEREABOUTS_RELEASE_URL ?? DEFAULT_SOURCE;
  if (value === DEFAULT_SOURCE)
    throw usage(
      "No release service is published yet; use --from DIR|URL or THEREABOUTS_RELEASE_URL",
    );
  if (!/^https?:\/\//.test(value)) return path.resolve(value);
  let parsed;
  try {
    parsed = new URL(value.endsWith("/") ? value : value + "/");
  } catch {
    throw usage("Invalid release URL");
  }
  validateUrl(parsed);
  return parsed;
}
function validateUrl(url) {
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.hash
  )
    throw usage("Use an HTTP(S) release URL without credentials or fragment");
}
async function request(url, headers = {}) {
  validateUrl(url);
  const controller = new AbortController();
  const dispatcher = new EnvHttpProxyAgent({
    httpProxy:
      process.env.http_proxy ??
      process.env.HTTP_PROXY ??
      process.env.all_proxy ??
      process.env.ALL_PROXY,
    httpsProxy:
      process.env.https_proxy ??
      process.env.HTTPS_PROXY ??
      process.env.all_proxy ??
      process.env.ALL_PROXY,
    connect: { timeout: HEADER_TIMEOUT_MS },
    headersTimeout: HEADER_TIMEOUT_MS,
    bodyTimeout: READ_TIMEOUT_MS,
  });
  try {
    for (let redirects = 0; ; redirects++) {
      const timer = setTimeout(
        () => controller.abort(new Error("Response headers timed out")),
        HEADER_TIMEOUT_MS,
      );
      let response;
      try {
        response = await fetch(url, {
          headers: {
            // Fetch appends identity for Range itself. Setting it twice sends
            // "identity, identity"; the loopback resume test asserts one value.
            ...(headers.Range ? {} : { "Accept-Encoding": "identity" }),
            ...headers,
          },
          redirect: "manual",
          signal: controller.signal,
          dispatcher,
        });
      } finally {
        clearTimeout(timer);
      }
      if (
        response.status >= 300 &&
        response.status < 400 &&
        response.headers.has("location")
      ) {
        await response.body?.cancel();
        const target = new URL(response.headers.get("location"), url);
        if (
          url.protocol !== "https:" ||
          target.protocol !== "https:" ||
          redirects >= 5
        )
          throw integrity("Unsafe or excessive HTTP redirect");
        validateUrl(target);
        url = target;
        continue;
      }
      if (
        (response.headers.get("content-encoding") ?? "identity") !== "identity"
      )
        throw integrity("Encoded download response");
      return { response, controller, dispatcher };
    }
  } catch (e) {
    controller.abort();
    await dispatcher.close();
    throw interrupted(e);
  }
}
async function* body(opened, maximum, readTimeout = READ_TIMEOUT_MS) {
  const { response, controller, dispatcher } = opened;
  const reader = response.body?.getReader();
  let total = 0;
  try {
    if (!reader) throw integrity("Missing response body");
    for (;;) {
      const timer = setTimeout(
        () => controller.abort(new Error("Download read stalled")),
        readTimeout,
      );
      let next;
      try {
        next = await reader.read();
      } finally {
        clearTimeout(timer);
      }
      if (next.done) break;
      total += next.value.length;
      if (total > maximum) throw integrity("Download exceeds advertised size");
      yield next.value;
    }
  } catch (e) {
    throw interrupted(e);
  } finally {
    await reader?.cancel().catch(() => {});
    controller.abort();
    await dispatcher.close();
  }
}
export async function index(origin) {
  let value;
  if (typeof origin === "string")
    value = readJson(safePath(origin, "index.json"));
  else {
    const opened = await request(new URL("index.json", origin));
    if (opened.response.status !== 200) {
      opened.controller.abort();
      await opened.dispatcher.close();
      throw integrity("Release index requires HTTP 200");
    }
    const chunks = [];
    for await (const chunk of body(opened, MAX_METADATA)) chunks.push(chunk);
    value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  }
  keys(value, ["format", "datasets"]);
  if (value.format !== 2) throw integrity("Requires release index format 2");
  keys(value.datasets, Object.keys(value.datasets ?? {}));
  for (const [version, dataset] of Object.entries(value.datasets)) {
    component(version);
    keys(dataset, ["packs"]);
    keys(dataset.packs, Object.keys(dataset.packs ?? {}));
    for (const [name, pack] of Object.entries(dataset.packs)) {
      component(name);
      keys(pack, ["url", "bytes", "sha256", "format_minor"]);
      if (
        !Number.isSafeInteger(pack.bytes) ||
        pack.bytes < 1 ||
        pack.bytes > 1024 ** 3 ||
        typeof pack.url !== "string" ||
        !pack.url ||
        typeof pack.sha256 !== "string" ||
        !/^[a-f\d]{64}$/.test(pack.sha256) ||
        !Number.isInteger(pack.format_minor)
      )
        throw integrity("Invalid release archive identity");
    }
  }
  return value;
}
export function compareVersions(a, b) {
  const left = a.split("."),
    right = b.split(".");
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    let result;
    if (
      /^\d+$/.test(left[i]) &&
      /^\d+$/.test(right[i]) &&
      BigInt(left[i]) <= 2n ** 64n - 1n &&
      BigInt(right[i]) <= 2n ** 64n - 1n
    ) {
      result =
        BigInt(left[i]) < BigInt(right[i])
          ? -1
          : BigInt(left[i]) > BigInt(right[i])
            ? 1
            : 0;
    } else result = Buffer.compare(Buffer.from(left[i]), Buffer.from(right[i]));
    if (result) return result;
  }
  return (
    left.length - right.length || Buffer.compare(Buffer.from(a), Buffer.from(b))
  );
}
export function select(value, requested, version) {
  requested.forEach(family);
  const candidates = Object.entries(value.datasets).filter(
    ([v, d]) =>
      (version === undefined || version === v) &&
      requested.every((f) => d.packs[f]?.format_minor === 2),
  );
  candidates.sort(([a], [b]) => compareVersions(b, a));
  if (!candidates.length)
    throw integrity("Requested dataset is unavailable or incompatible");
  return candidates[0];
}
export async function* archive(
  origin,
  pack,
  offset,
  readTimeout = READ_TIMEOUT_MS,
) {
  if (typeof origin === "string") {
    const filename = safePath(origin, pack.url);
    if (fs.statSync(filename).size !== pack.bytes)
      throw integrity("Local archive size mismatch");
    yield* fs.createReadStream(filename, { start: offset });
    return;
  }
  const url = new URL(pack.url, origin);
  if (
    !["https:", "http:"].includes(url.protocol) ||
    (origin.protocol === "https:" && url.protocol !== "https:")
  )
    throw integrity("Unsafe archive URL");
  const opened = await request(
    url,
    offset ? { Range: `bytes=${offset}-` } : {},
  );
  const response = opened.response;
  const length = response.headers.get("content-length");
  if (
    response.status !== (offset ? 206 : 200) ||
    (offset &&
      response.headers.get("content-range") !==
        `bytes ${offset}-${pack.bytes - 1}/${pack.bytes}`) ||
    (length !== null && length !== String(pack.bytes - offset))
  ) {
    opened.controller.abort();
    await opened.dispatcher.close();
    throw integrity("Invalid download status, length or resume range");
  }
  yield* body(opened, pack.bytes - offset, readTimeout);
}
