# Historical serving format

The previous `thereabouts-pack-1` spatial/catalogue and exact-code format is
retained only by the legacy Python and JavaScript readers during migration.
Its full historical specification is available in this file at commit
`3ade5da` (`git show 3ade5da:docs/SERVING_FORMAT.md`).

[PACK_FORMAT.md](PACK_FORMAT.md) is the single normative specification for new
format-2 core packs. Format 2 adds catalogue points, population and timezones,
per-cell timezone sets, and country/subdivision/zone metadata. Old packs are
reported as incompatible by the new public API. They are not silently converted.
