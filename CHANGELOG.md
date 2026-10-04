# Changelog

## 0.1.0 — draft, unpublished

- One Rust core owns format 2.2, results, reverse and all forward lookups.
- Python abi3 bindings and Node ESM/WASM expose the same result semantics.
- Explicit CLI verbs, streaming batch input, four output formats and shared stores.
- Resumable explicit installation, checksums, catalogue pins and atomic activation.
- Dictionary-coded, compressed forward blocks; shared core catalogue; lazy evidence.
- Grouped and legacy cell-layout inputs; real pipeline writer integration and
  deterministic installable release archives.
- Retired the v1 runtime, Python binary reader, Cython extension and hand-written
  Node reader. Old binary packs require rebuilding; they are not silently converted.
- Ambiguity keeps agreed flat fields. Reverse reports distance bands.
- Added wheel, sdist, npm and synthetic pipeline workflows. Publication is gated
  by an explicit manual run on a matching tag and release-environment approval.

The owner publishes 0.1.0 to supersede the PyPI/npm 0.0.1 placeholders.
No registry release has been made by this work. Code licensing and public release
endpoint remain owner decisions; the real names and plate-table gaps are recorded
in docs/clients/status.md.
