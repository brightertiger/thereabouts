import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import { createHash } from "node:crypto";
import { install } from "../runtime/install.js";
import { source } from "../runtime/transport.js";
import { release } from "./release.js";
import { temporary, console } from "./helpers.js";

// A loopback server that records each request's path, Range, Accept and Authorization.
async function server(t, route) {
  const seen = [];
  const service = http.createServer((request, response) => {
    seen.push({
      path: request.url,
      range: request.headers.range ?? null,
      accept: request.headers.accept ?? null,
      authorization: request.headers.authorization ?? null,
    });
    route(request, response);
  });
  await new Promise((resolve) => service.listen(0, "127.0.0.1", resolve));
  t.after(
    () =>
      new Promise((resolve) => {
        service.closeAllConnections();
        service.close(resolve);
      }),
  );
  return { url: new URL(`http://127.0.0.1:${service.address().port}/`), seen };
}
function redirect(response, location) {
  response.writeHead(302, { Location: location, "Content-Length": 0 });
  response.end();
}
// GitHub's object host: Range on the archive, the first transfer optionally cut.
async function objects(t, fixture, index, cut = false) {
  let first = cut;
  return server(t, (request, response) => {
    if (request.url.startsWith("/2/")) {
      response.end(JSON.stringify(index));
      return;
    }
    const offset = Number(
      request.headers.range?.match(/^bytes=(\d+)-$/)?.[1] ?? 0,
    );
    const total = fixture.bytes.length;
    response.writeHead(offset ? 206 : 200, {
      "Content-Length": total - offset,
      ...(offset
        ? { "Content-Range": `bytes ${offset}-${total - 1}/${total}` }
        : {}),
    });
    if (first) {
      first = false;
      response.write(fixture.bytes.subarray(0, 1024));
      setTimeout(() => response.destroy(), 30);
      return;
    }
    response.end(fixture.bytes.subarray(offset));
  });
}

test("a public GitHub release installs through redirects with Range and no credentials", async (t) => {
  const root = temporary(t),
    fixture = release(path.join(root, "release")),
    store = path.join(root, "store");
  const index = structuredClone(fixture.index);
  const store_ = await objects(t, fixture, index, true);
  const web = await server(t, (request, response) => {
    if (request.url === "/o/r/releases/latest/download/index.json")
      redirect(response, "/o/r/releases/download/v1/index.json");
    else if (request.url === "/o/r/releases/download/v1/index.json")
      redirect(response, new URL("/2/index.json", store_.url).href);
    else if (request.url === "/o/r/releases/download/v1/phone.tar.zst")
      redirect(response, new URL("/1/phone.tar.zst", store_.url).href);
    else {
      response.writeHead(404);
      response.end();
    }
  });
  const pack = index.datasets[fixture.version].packs.phone;
  pack.url = new URL("o/r/releases/download/v1/phone.tar.zst", web.url).href;
  pack.api_url = "https://api.github.invalid/repos/o/r/releases/assets/1";
  const origin = source(
    new URL("o/r/releases/latest/download/", web.url).href,
    {},
  );
  await assert.rejects(
    install(store, origin, ["phone"]),
    /Download interrupted/,
  );
  const pin = await install(store, origin, ["phone"]);
  assert.equal(pin.data_version, fixture.version);
  const all = [...web.seen, ...store_.seen];
  assert.ok(all.every((r) => r.authorization === null));
  // Both hops of each attempt carry the same Range: web redirect, then objects.
  for (const seen of [web.seen, store_.seen])
    assert.deepEqual(
      seen.filter((r) => r.path.endsWith("phone.tar.zst")).map((r) => r.range),
      [null, "bytes=1024-"],
    );
});

test("a token reads a private release through the API and never forwards it", async (t) => {
  const root = temporary(t),
    fixture = release(path.join(root, "release")),
    store = path.join(root, "store");
  const index = structuredClone(fixture.index);
  const store_ = await objects(t, fixture, index);
  const web = await server(t, (request, response) => {
    response.writeHead(404);
    response.end();
  });
  const api = await server(t, (request, response) => {
    if (request.headers.authorization !== "Bearer secret") {
      response.writeHead(404);
      response.end();
    } else if (request.url === "/repos/o/r/releases/latest")
      response.end(
        JSON.stringify({ id: 5, assets: [{ id: 2, name: "index.json" }] }),
      );
    else if (request.url === "/repos/o/r/releases/assets/2")
      redirect(response, new URL("/2/index.json", store_.url).href);
    else if (request.url === "/repos/o/r/releases/assets/1")
      redirect(response, new URL("/1/phone.tar.zst", store_.url).href);
    else {
      response.writeHead(404);
      response.end();
    }
  });
  const pack = index.datasets[fixture.version].packs.phone;
  pack.url = new URL("o/r/releases/download/v1/phone.tar.zst", web.url).href;
  pack.api_url = new URL("repos/o/r/releases/assets/1", api.url).href;
  const env = {
    GITHUB_TOKEN: "secret",
    THEREABOUTS_GITHUB_API_URL: api.url.href,
  };
  const origin = source(
    new URL("o/r/releases/latest/download/", web.url).href,
    env,
  );
  await install(store, origin, ["phone"]);
  assert.equal(web.seen.length, 0);
  assert.ok(api.seen.every((r) => r.authorization === "Bearer secret"));
  const asset = api.seen.find((r) => r.path.endsWith("/assets/1"));
  assert.equal(asset.accept, "application/octet-stream");
  assert.ok(
    store_.seen.length === 2 &&
      store_.seen.every((r) => r.authorization === null),
  );
  assert.throws(
    () =>
      source("https://github.com/o/r/releases/latest/download/", {
        THEREABOUTS_RELEASE_TOKEN: "secret",
        THEREABOUTS_GITHUB_API_URL: "http://api.example.com",
      }),
    /THEREABOUTS_GITHUB_API_URL/,
  );
  const mirror = source(new URL("mirror/", web.url).href, env);
  await assert.rejects(install(path.join(root, "other"), mirror, ["phone"]));
  assert.ok(web.seen.every((r) => r.authorization === null));
});

// A stored zip in the layout the pipeline writes.
const CRC = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(bytes) {
  let c = 0xffffffff;
  for (const b of bytes) c = CRC[(c ^ b) & 255] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function zip(entries) {
  const parts = [],
    central = [];
  let offset = 0;
  for (const [name, data] of entries) {
    const header = (signature, size) => {
      const b = Buffer.alloc(size);
      b.writeUInt32LE(signature, 0);
      return b;
    };
    const local = header(0x04034b50, 30);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x21, 12);
    local.writeUInt32LE(crc32(data), 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(name.length, 26);
    const record = header(0x02014b50, 46);
    record.writeUInt16LE(0x0314, 4);
    record.writeUInt16LE(20, 6);
    record.writeUInt16LE(0x21, 14);
    record.writeUInt32LE(crc32(data), 16);
    record.writeUInt32LE(data.length, 20);
    record.writeUInt32LE(data.length, 24);
    record.writeUInt16LE(name.length, 28);
    record.writeUInt32LE((0o100644 << 16) >>> 0, 38);
    record.writeUInt32LE(offset, 42);
    parts.push(local, Buffer.from(name), data);
    central.push(record, Buffer.from(name));
    offset += 30 + name.length + data.length;
  }
  const directory = Buffer.concat(central),
    end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...parts, directory, end]);
}
const sha = (bytes) => createHash("sha256").update(bytes).digest("hex");
function datasetRelease(root, digest = null) {
  fs.mkdirSync(root, { recursive: true });
  const cells = [
    ["cells/group=8165bffffffffff/part.parquet", Buffer.from("cells parquet")],
    ["cells/group=81653ffffffffff/part.parquet", Buffer.from("more cells")],
  ];
  const readme = Buffer.from("# Dataset\n"),
    archive = zip(cells),
    base = "https://github.com/o/r/releases/download/v2026.10";
  fs.writeFileSync(path.join(root, "dataset-cells.zip"), archive);
  fs.writeFileSync(path.join(root, "README.md"), readme);
  const manifest = Buffer.from(
    JSON.stringify({
      format: 1,
      version: "2026.10",
      archives: [
        {
          name: "dataset-cells.zip",
          table: "cells",
          url: `${base}/dataset-cells.zip`,
          size: archive.length,
          sha256: sha(archive),
          unpacked_size: 23,
          files: cells.map(([name, data]) => ({
            path: name,
            size: data.length,
            sha256: digest ?? sha(data),
          })),
        },
      ],
      files: [
        {
          path: "README.md",
          url: `${base}/README.md`,
          size: readme.length,
          sha256: sha(readme),
        },
      ],
    }),
  );
  fs.writeFileSync(path.join(root, "dataset-manifest.json"), manifest);
  const index = {
    format: 3,
    datasets: {
      "2026.10": {
        packs: {},
        dataset: {
          url: `${base}/dataset-manifest.json`,
          size: manifest.length,
          sha256: sha(manifest),
        },
      },
    },
  };
  fs.writeFileSync(path.join(root, "index.json"), JSON.stringify(index));
  return cells;
}

test("data install dataset restores the dataset tree, all or nothing", async (t) => {
  const root = temporary(t),
    from = path.join(root, "release"),
    store = path.join(root, "store");
  const cells = datasetRelease(from);
  const first = console(store, [
    "data",
    "install",
    "dataset",
    "--from",
    from,
    "--json",
  ]);
  assert.equal(first.status, 0, first.stderr);
  assert.equal(JSON.parse(first.stdout).dataset.installed, true);
  const tree = path.join(store, "dataset/2026.10");
  for (const [name, data] of cells)
    assert.deepEqual(fs.readFileSync(path.join(tree, name)), data);
  assert.equal(
    fs.readFileSync(path.join(tree, "README.md"), "utf8"),
    "# Dataset\n",
  );
  assert.deepEqual(fs.readdirSync(path.join(store, ".downloads")), []);
  const again = console(store, [
    "data",
    "install",
    "dataset",
    "--from",
    from,
    "--json",
  ]);
  assert.equal(JSON.parse(again.stdout).dataset.installed, false);
  const mixed = console(store, [
    "data",
    "install",
    "dataset",
    "core",
    "--from",
    from,
  ]);
  assert.equal(mixed.status, 2);
  assert.match(mixed.stderr, /on its own/);
  const broken = path.join(root, "broken");
  datasetRelease(broken, "0".repeat(64));
  const other = path.join(root, "other");
  const refused = console(other, [
    "data",
    "install",
    "dataset",
    "--from",
    broken,
  ]);
  assert.equal(refused.status, 4, refused.stderr);
  assert.match(refused.stderr, /differs from the dataset manifest/);
  assert.ok(!fs.existsSync(path.join(other, "dataset")));
});
