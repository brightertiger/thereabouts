// Transfer policy is host-owned; lookup modules never import this file.
import fs from "node:fs";
import path from "node:path";
import { EnvHttpProxyAgent } from "undici";
import { safePath } from "./host.js";
import { MAX_METADATA, readJson, component, family } from "./store.js";
import {
  integrity,
  usage,
  IncompatibleDataError,
  ThereaboutsError,
} from "./errors.js";
import { wasm } from "./wasm.js";
export function interrupted(error) {
  if (error instanceof ThereaboutsError || error.exitCode !== undefined)
    return error;
  return usage(
    `Download interrupted; run the same data install again to resume: ${error.message}`,
  );
}
// Caps and the default URL are defined once in Rust and read through WASM.
const policy = JSON.parse((await wasm()).transport());
export const DEFAULT_SOURCE = policy.default_release_url,
  MAX_ARCHIVE_BYTES = policy.max_archive_bytes,
  MAX_UNPACKED_BYTES = policy.max_unpacked_bytes,
  INDEX_FORMAT = policy.index_format,
  ARCHIVE_SUFFIX = policy.archive_suffix,
  DATASET_MANIFEST = policy.dataset_manifest,
  DATASET_MANIFEST_FORMAT = policy.dataset_manifest_format;
export const HEADER_TIMEOUT_MS = 30_000,
  READ_TIMEOUT_MS = 60_000;
const BINARY = "application/octet-stream",
  API_JSON = "application/vnd.github+json",
  ASSET_PAGES = 10;
// Token mode rides on the release URL object, out of its string form and JSON.
const GITHUB = Symbol("github");
export function source(explicit, env = process.env) {
  const value = explicit ?? env.THEREABOUTS_RELEASE_URL ?? DEFAULT_SOURCE;
  if (!/^https?:\/\//.test(value)) return path.resolve(value);
  let parsed;
  try {
    parsed = new URL(value.endsWith("/") ? value : value + "/");
  } catch {
    throw usage("Invalid release URL");
  }
  validateUrl(parsed);
  // A token reads private GitHub releases through the API; it goes nowhere else.
  const token = policy.token_variables.map((name) => env[name]).find(Boolean);
  const github =
    token &&
    githubRelease(
      parsed,
      env[policy.github_api_variable] ?? policy.github_api_url,
      token,
    );
  if (github) Object.defineProperty(parsed, GITHUB, { value: github });
  return parsed;
}
function loopback(hostname) {
  return ["localhost", "127.0.0.1", "[::1]", "::1"].includes(hostname);
}
// `<owner>/<repo>/releases/latest/download` or `.../releases/download/<tag>`.
function githubRelease(url, api, token) {
  const parts = url.pathname.replace(/^\/+|\/+$/g, "").split("/");
  if (parts.length !== 5 || parts[2] !== "releases") return null;
  let release;
  if (parts[3] === "latest" && parts[4] === "download") release = "latest";
  else if (parts[3] === "download" && parts[4]) release = `tags/${parts[4]}`;
  else return null;
  let base;
  try {
    base = new URL(api);
  } catch {
    base = null;
  }
  if (
    !base ||
    base.username ||
    base.password ||
    !(
      base.protocol === "https:" ||
      (base.protocol === "http:" && loopback(base.hostname))
    )
  )
    throw usage(
      `${policy.github_api_variable} must be an HTTPS URL (plain HTTP only on loopback)`,
    );
  return {
    api: base.href.replace(/\/+$/, ""),
    origin: base.origin,
    repository: `${parts[0]}/${parts[1]}`,
    release,
    token,
  };
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
async function request(url, headers = {}, github = null) {
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
      // Credentials go only to the GitHub API origin, never across a redirect.
      const credentials =
        github && url.origin === github.origin
          ? {
              Authorization: `Bearer ${github.token}`,
              "X-GitHub-Api-Version": policy.github_api_version,
            }
          : {};
      try {
        response = await fetch(url, {
          headers: {
            // Fetch appends identity for Range itself. Setting it twice sends
            // "identity, identity"; the loopback resume test asserts one value.
            ...(headers.Range ? {} : { "Accept-Encoding": "identity" }),
            ...headers,
            ...credentials,
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
        // HTTPS anywhere; plain HTTP only from loopback to loopback.
        const allowed =
          target.protocol === "https:" ||
          (url.protocol === "http:" &&
            target.protocol === "http:" &&
            loopback(target.hostname));
        if (!allowed || redirects >= 5)
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
// A bounded metadata document: an index, a release or an asset listing.
async function metadata(url, accept = null, github = null) {
  const opened = await request(url, accept ? { Accept: accept } : {}, github);
  if (opened.response.status !== 200) {
    opened.controller.abort();
    await opened.dispatcher.close();
    throw integrity("Release index requires HTTP 200");
  }
  const chunks = [];
  for await (const chunk of body(opened, MAX_METADATA)) chunks.push(chunk);
  return Buffer.concat(chunks);
}
// The index asset's id: listed in the release, or on one of its asset pages.
async function indexAsset(github, release) {
  const named = (assets) =>
    Array.isArray(assets)
      ? assets.find((a) => a?.name === "index.json")?.id
      : undefined;
  const listed = named(release.assets);
  if (Number.isSafeInteger(listed)) return listed;
  if (!Number.isSafeInteger(release.id))
    throw integrity("Invalid GitHub release response");
  for (let page = 1; page <= ASSET_PAGES; page++) {
    const url = new URL(
      `${github.api}/repos/${github.repository}/releases/${release.id}/assets?per_page=100&page=${page}`,
    );
    const assets = JSON.parse(await metadata(url, API_JSON, github));
    const id = named(assets);
    if (Number.isSafeInteger(id)) return id;
    if (!Array.isArray(assets) || assets.length < 100) break;
  }
  throw integrity("The GitHub release has no index.json");
}
async function fetchIndex(origin) {
  const github = origin[GITHUB];
  if (!github) return metadata(new URL("index.json", origin));
  const releases = `${github.api}/repos/${github.repository}/releases`;
  const release = JSON.parse(
    await metadata(new URL(`${releases}/${github.release}`), API_JSON, github),
  );
  const id = await indexAsset(github, release);
  return metadata(new URL(`${releases}/assets/${id}`), BINARY, github);
}
function digest(value) {
  return typeof value === "string" && /^[a-f\d]{64}$/.test(value);
}
export async function index(origin) {
  let value;
  if (typeof origin === "string")
    value = readJson(safePath(origin, "index.json"));
  else value = JSON.parse((await fetchIndex(origin)).toString("utf8"));
  // Unknown fields are ignored at every level; required fields are validated.
  object(value);
  if (value.format !== INDEX_FORMAT)
    throw new IncompatibleDataError(
      `Requires release index format ${INDEX_FORMAT}, found ${value.format}; use a matching client`,
    );
  object(value.datasets);
  for (const [version, dataset] of Object.entries(value.datasets)) {
    component(version);
    object(dataset);
    object(dataset.packs);
    for (const [name, pack] of Object.entries(dataset.packs)) {
      component(name);
      object(pack);
      if (
        !Number.isSafeInteger(pack.size) ||
        pack.size < 1 ||
        pack.size > MAX_ARCHIVE_BYTES ||
        !Number.isSafeInteger(pack.unpacked_size) ||
        pack.unpacked_size < 1 ||
        pack.unpacked_size > MAX_UNPACKED_BYTES ||
        typeof pack.url !== "string" ||
        !pack.url ||
        !digest(pack.sha256) ||
        !Number.isInteger(pack.format_minor)
      )
        throw integrity("Invalid release archive identity");
    }
    if (dataset.dataset !== undefined) {
      const file = dataset.dataset;
      object(file);
      if (
        !Number.isSafeInteger(file.size) ||
        file.size < 1 ||
        file.size > MAX_METADATA ||
        typeof file.url !== "string" ||
        !file.url ||
        !digest(file.sha256)
      )
        throw integrity("Invalid dataset manifest identity");
    }
  }
  return value;
}
function object(value) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw integrity("Invalid release index");
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
// Newest release (or the requested one) that ships the Parquet dataset.
export function selectDataset(value, version) {
  const candidates = Object.entries(value.datasets).filter(
    ([v, d]) => d.dataset && (version === undefined || version === v),
  );
  candidates.sort(([a], [b]) => compareVersions(b, a));
  if (!candidates.length)
    throw integrity(
      version === undefined
        ? "No release ships the dataset"
        : "Requested release does not ship the dataset",
    );
  return [candidates[0][0], candidates[0][1].dataset];
}
// A downloaded GitHub release keeps its flat asset names: an absolute URL in its
// index names a file in the directory by its last path segment.
function localName(name) {
  return /^https?:\/\//.test(name) ? name.split("/").at(-1) : name;
}
// One release file ({url, api_url?, size}) from `offset`; resumes use Range.
export async function* archive(
  origin,
  pack,
  offset,
  readTimeout = READ_TIMEOUT_MS,
) {
  if (typeof origin === "string") {
    const filename = safePath(origin, localName(pack.url));
    if (fs.statSync(filename).size !== pack.size)
      throw integrity("Local archive size mismatch");
    yield* fs.createReadStream(filename, { start: offset });
    return;
  }
  const github = origin[GITHUB];
  let url, accept;
  if (
    github &&
    typeof pack.api_url === "string" &&
    URL.canParse(pack.api_url) &&
    new URL(pack.api_url).origin === github.origin
  ) {
    url = new URL(pack.api_url);
    accept = { Accept: BINARY };
  } else {
    url = new URL(pack.url, origin);
    if (
      !["https:", "http:"].includes(url.protocol) ||
      (origin.protocol === "https:" && url.protocol !== "https:")
    )
      throw integrity("Unsafe archive URL");
  }
  const opened = await request(
    url,
    { ...(offset ? { Range: `bytes=${offset}-` } : {}), ...accept },
    github,
  );
  const response = opened.response;
  const length = response.headers.get("content-length");
  if (
    response.status !== (offset ? 206 : 200) ||
    (offset &&
      response.headers.get("content-range") !==
        `bytes ${offset}-${pack.size - 1}/${pack.size}`) ||
    (length !== null && length !== String(pack.size - offset))
  ) {
    opened.controller.abort();
    await opened.dispatcher.close();
    throw integrity("Invalid download status, length or resume range");
  }
  yield* body(opened, pack.size - offset, readTimeout);
}
