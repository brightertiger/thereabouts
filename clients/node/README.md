# Thereabouts for Node

An independent, asynchronous JavaScript reader for Thereabouts reverse, postal
and airport serving packs. Requires Node 22 or 24. Runtime dependency: `h3-js`
4.5.0 for H3 conversion and validity checks; no Python, compiler, native addon or
build step is required. This unreleased package is private pending the owner's
code and data licence decisions. It contains no geographic dataset.

```js
import {Geocoder, requireOne} from 'thereabouts';

const geo = await Geocoder.open({pack: '/data/reverse-pack'});
try {
  const answer = await geo.reverse(12.97, 77.59);
  console.log(requireOne(answer)?.city?.name ?? null);
  console.log(await geo.fromH3('8860145b4bfffff'));
  for await (const row of geo.reverseMany([[12.97, 77.59], [0, 180]])) {
    console.log(JSON.stringify(row));
  }
} finally {
  await geo.close();
}
```

`Geocoder.open({packs: {postal: '/data/postal', airports: '/data/airports'}})`
selects compatible optional packs. Use `postal('00100', {country: 'AA'})` and
`airport('ZZZ', {scheme: 'iata'})`; `local` airport codes also need a country.
No country or airport scheme is inferred. Manifest rules determine code
normalization. Leading zeros, source observations, unlocated entities, multiple
candidates, methods and distance bands match Python's JSON results. Ambiguous
results have `selected: null`; `requireOne` raises `AmbiguousResultError`.

Results are deeply frozen and remain usable after close. `structuredClone`
provides a mutable copy. `info()` returns detached manifests and cache counters;
`explain(result)` returns `{result, raw_evidence_installed: false}`. Coordinates
must be finite numbers in latitude ±90 / longitude ±180; +180 becomes -180.
H3 inputs must be resolution-8 hexadecimal strings. H3 identities never pass
through JavaScript Number. Unknown geography returns a status, not an exception.

`reverseMany` and `fromH3Many` accept synchronous or asynchronous iterables and
preserve order. They consume one input at a time. `errors: 'collect'` emits an
`invalid_input` result for a malformed row; data errors still reject the iterator.
Default `errors: 'raise'` rejects invalid input. Batches yield to the event loop
every 256 results, configurable with positive `chunkSize`. Close rejects new
queries, waits for active reads and invalidates suspended iterators. Node does
not yet expose Python's NumPy column interface.

## Explicit local installation

Lookups and opening never access the network. Transfer a pack directory and a
trusted manifest SHA256 through an operator-controlled channel, then import it:

```js
import {importPack, verifyPack, Geocoder} from 'thereabouts';

const path = await importPack('/media/postal-pack', {
  dataDir: '/data/thereabouts',
  manifestSha256: '<trusted 64-digit lowercase SHA256>',
});
await verifyPack(path);
const geo = await Geocoder.open({dataDir: '/data/thereabouts', packs: ['postal']});
try { console.log(await geo.postal('00100', {country: 'AA'})); }
finally { await geo.close(); }
```

Import verifies hashes and structure before and after copying, publishes by
atomic rename and updates the family pointer atomically. Concurrent complete
imports can activate in completion order. Existing readers retain their version;
old installations remain. Interrupted copies use isolated staging and are removed
on ordinary errors; after process termination an abandoned `.import-*` directory
may be removed explicitly. Node imports do not resume partial copies.

The persistent store is shared with Python: explicit `dataDir`, then
`THEREABOUTS_DATA`, then `~/Library/Application Support/Thereabouts` on macOS,
`%LOCALAPPDATA%/Thereabouts` on Windows or `$XDG_DATA_HOME/thereabouts` (default
`~/.local/share/thereabouts`) on Linux. Family selection defaults to reverse.
Packs opened together must share catalogue epoch, golden/policy digests and H3
version. Use Python's explicit installer for pinned URL transfers and its CLI to
list installations; Node supports local import and full verification only.

Normal open checks inventory, sizes and binary directories. `verify: true`
additionally checks all hashes and payload structures. Keep packs immutable.
The format is specified in [FORMAT.md](FORMAT.md), copied from the repository's
`docs/SERVING_FORMAT.md` with repository cross-references labelled; tests check the copy.

## Resource model and measurements

File reads are asynchronous, in 64 KiB pages. File handles close after each read;
no world table or complete catalogue is loaded. Default `cacheBytes: 33554432`
is a combined cache accounting budget, divided equally between selected packs;
each pack assigns one quarter to raw pages/blocks and three quarters to decoded
places/candidates. Zero disables caching. Raw buffers are charged by length,
objects by a conservative retained-graph estimate with shared objects counted
again across entries. This is not a JavaScript heap or process RSS limit; results
retained by the caller, H3 memory and active reads are additional. Metadata scales
with the manifest and at most 41,162 block entries per reverse pack.

On Apple M2, 8 GiB RAM, macOS 27 arm64, Node 24.21.0/H3-JS 4.5.0, a synthetic
4,176-place / 308,032-row / 64-block pack occupies 3,006,380 bytes. Across 44,032
shuffled coordinates: warm scalar median **8.583 µs**, p99 **16.583 µs**; five
object-batch runs **105,022–110,640 results/s**, median **108,583/s**. Open took
**9.125 ms**, first query **10.870 ms** and the first pass **54,589 results/s**.
This was an empty reader cache, not a flushed operating-system disk cache.
Peak RSS was **176,553,984 bytes**. Retained cache accounting was 4,757,630 raw
and 18,086,650 decoded bytes, with no evictions after the full working set was
read. The initial equal cache split evicted decoded places; measured residency
motivated the final split.

Event-loop delay (5 ms sampling) was first-pass p99/max **10.002/10.568 ms** and
warm object-batch p99/max **7.279/8.937 ms**. Validation yields every 256 keys too;
an initial synchronous-validation run reached a 161 ms maximum. These are noisy
single-machine observations while another pipeline was active, not Node service
latency guarantees, geographic accuracy evidence or world-pack forecasts.
The exact report and reproduction commands are in the repository's
`docs/CLIENT_NODE_MEASUREMENTS.json` and `docs/CLIENT_STATUS.md`.

## Development

`npm ci --ignore-scripts`, `npm test`, `npm run check`, `npm run format`.
TypeScript only checks the public declarations and usage examples; shipped JS
runs directly. Prettier is the development formatter. Runtime tests block network
connections and use `node --test`. The shared bundle tests full Python-generated
JSON results and errors, malformed headers/manifests, Unicode, code multiplicity,
all city methods and logical ancestors. Additional tests exhaust three blocks
including a pentagon and a pole, uint16 dictionaries, cache eviction/disable,
close during reads, concurrent import, symlinks and zlib trailing streams.
