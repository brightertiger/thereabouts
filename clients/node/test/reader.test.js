import { test } from "node:test";
import assert from "node:assert/strict";
import h3 from "h3-js";
import { fileURLToPath } from "node:url";
import {
  Geocoder,
  ClosedReaderError,
  InvalidInputError,
  IncompatibleDataError,
} from "../src/index.js";
import { address, storedCell, OFFSETS } from "../src/address.js";
import { Cache } from "../src/cache.js";
import { loadBlock, lookup } from "../src/spatial.js";

const fixtures = fileURLToPath(
  new URL("../../../tests/fixtures/", import.meta.url),
);
const pack = `${fixtures}/serving`;
test("bounded caches, disabled parity and detached immutable results", async () => {
  const cached = await Geocoder.open({ pack, cacheBytes: 16384 });
  const disabled = await Geocoder.open({ pack, cacheBytes: 0 });
  const cell = h3.cellToCenterChild(
    h3.cellToChildren(h3.latLngToCell(12.97, 77.59, 3), 4)[0],
    8,
  );
  try {
    const expected = await disabled.fromH3(cell);
    for (let i = 0; i < 3; i++)
      assert.deepEqual(await cached.fromH3(cell), expected);
    for (const cache of Object.values(cached.info().cache.reverse))
      assert.ok(cache.retained_bytes <= cache.budget_bytes);
    assert.equal(disabled.info().cache.reverse.decoded.retained_bytes, 0);
    const answer = await cached.fromH3(cell);
    assert.throws(() => {
      answer.selected.city.name = "edited";
    }, TypeError);
    const info = cached.info();
    info.packs.reverse.sources.length = 0;
    assert.equal(cached.info().packs.reverse.sources.length, 1);
    await cached.close();
    assert.deepEqual(answer, expected);
  } finally {
    await cached.close();
    await disabled.close();
  }
});
test("batch order, collect, async source and early termination", async () => {
  const reader = await Geocoder.open({ pack });
  try {
    const points = [
      [12.97, 77.59],
      [91, 0],
      [0, 180],
      [-90, 0],
    ];
    const rows = [];
    for await (const row of reader.reverseMany(points, {
      errors: "collect",
      chunkSize: 1,
    }))
      rows.push(row);
    assert.equal(rows[1].status, "invalid_input");
    assert.equal(rows[1].query.latitude, null);
    for (const index of [0, 2, 3])
      assert.deepEqual(rows[index], await reader.reverse(...points[index]));
    let consumed = 0;
    async function* source() {
      for (const point of points) {
        consumed++;
        yield point;
      }
    }
    for await (const row of reader.reverseMany(source())) {
      assert.equal(row.status, "matched");
      break;
    }
    assert.equal(consumed, 1);
    await assert.rejects(async () => {
      for await (const row of reader.reverseMany(points)) void row;
    }, InvalidInputError);
    await assert.rejects(
      reader.fromH3Many([], { chunkSize: 0 }).next(),
      InvalidInputError,
    );
  } finally {
    await reader.close();
  }
});
test("close waits for pending reads and invalidates suspended batches", async () => {
  const reader = await Geocoder.open({ pack });
  const query = reader.reverse(12.97, 77.59);
  const closing = reader.close();
  assert.equal((await query).status, "matched");
  await closing;
  await assert.rejects(reader.reverse(0, 0), ClosedReaderError);
  await reader.close();
  const another = await Geocoder.open({ pack });
  const batch = another.reverseMany([
    [0, 180],
    [0, 180],
  ]);
  await batch.next();
  await another.close();
  await assert.rejects(batch.next(), ClosedReaderError);
});
test("source callback can close reader without deadlock or reopening files", async () => {
  const reader = await Geocoder.open({ pack });
  async function* source() {
    await reader.close();
    yield [0, 0];
  }
  await assert.rejects(reader.reverseMany(source()).next(), ClosedReaderError);
});
test("compatible families and incompatible epochs are explicit", async () => {
  const reader = await Geocoder.open({
    packs: {
      reverse: `${fixtures}/codes/reverse`,
      postal: `${fixtures}/codes/postal`,
      airports: `${fixtures}/codes/airports`,
    },
  });
  try {
    assert.equal(
      (await reader.postal("00100", { country: "AA" })).status,
      "matched",
    );
  } finally {
    await reader.close();
  }
  await assert.rejects(
    Geocoder.open({
      packs: { reverse: pack, postal: `${fixtures}/codes/postal` },
    }),
    IncompatibleDataError,
  );
});
test("exhaust all descendants including pentagon, pole and sparse ancestor misses", async () => {
  const reader = await Geocoder.open({ pack });
  try {
    for (const root of [
      h3.latLngToCell(12.97, 77.59, 3),
      h3.getPentagons(3)[0],
      h3.latLngToCell(-89.99, 0, 3),
    ]) {
      for (const cell of h3.cellToChildren(root, 8)) {
        const { block, suffix } = address(cell);
        for (let depth = 0; depth <= 5; depth++) {
          const key = OFFSETS[depth] + Math.floor(suffix / 7 ** (5 - depth));
          assert.equal(
            storedCell(block, key),
            h3.cellToParent(cell, depth + 3),
          );
        }
        const result = await reader.fromH3(cell);
        const stored = result.reference.stored_h3;
        if (stored)
          assert.equal(
            stored,
            h3.cellToParent(cell, result.reference.stored_resolution),
          );
      }
    }
  } finally {
    await reader.close();
  }
});
test("uint16 dictionaries and unaligned values decode numerical labels", async () => {
  const root = h3.latLngToCell(12.97, 77.59, 3);
  const cells = h3.cellToChildren(root, 8).slice(0, 300);
  const keys = Buffer.alloc(600),
    values = Buffer.alloc(600),
    dictionary = Buffer.alloc(300 * 16);
  cells.forEach((cell, i) => {
    keys.writeUInt16LE(OFFSETS[5] + address(cell).suffix, i * 2);
    values.writeUInt16LE(i, i * 2);
    dictionary.writeUInt32LE(i + 1, i * 16 + 8);
    dictionary.writeUInt32LE(1, i * 16 + 12);
  });
  const bytes = Buffer.concat([Buffer.alloc(1), keys, values, dictionary]);
  const entry = {
    block: address(cells[0]).block,
    count: 300,
    width: 2,
    labels: 300,
    keys: 0,
    values: 0,
    dictionary: 0,
    shard: {
      file: {
        read: async (start, length) => bytes.subarray(start, start + length),
      },
      sections: { 2: { start: 1 }, 3: { start: 601 }, 4: { start: 1201 } },
    },
  };
  const loaded = await loadBlock(entry, new Cache(0), 300);
  for (const [i, cell] of cells.entries())
    assert.deepEqual(lookup(entry, loaded, address(cell).suffix).label, [
      0,
      0,
      i + 1,
      1,
    ]);
});
