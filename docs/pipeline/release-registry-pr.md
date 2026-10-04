# Registry pull request draft

Owner draft only. Do not submit while the resource fields contain placeholders
or before anonymous reads and the registry's own schema/CI checks pass. No pull
request or cloud publication was made during pipeline implementation.

Suggested title: **Add Thereabouts offline geocoding dataset**

Suggested description, to complete after staging acceptance:

> Add Thereabouts, a versioned Parquet database connecting geographic coordinates
> and location identifiers to countries, subdivisions and selected settlements.
> Tables retain original names, source observations, provenance, ambiguity and
> assignment methods alongside reviewed canonical city/town allocation.
>
> The dataset includes H3 resolution-8 land/near-shore coverage stored with
> lossless compaction, place catalogues, postal observations, airport identifiers,
> UN/LOCODE observations, IP ranges, telephone metadata and timezone membership.
> Cell files are grouped for direct object-storage reads. README examples cover
> DuckDB, PyArrow and pandas; manifest SHA256 and logical table digests support
> verification and comparisons between monthly releases.
>
> The derived database is distributed under ODbL 1.0. Per-source notices include
> © OpenStreetMap contributors, Overture Maps Foundation, GeoNames and the other
> contributing sources listed in `DATA_LICENSES.md`. Public derivative database
> use remains subject to ODbL attribution and share-alike terms.
>
> Public bucket: **OWNER DECISION — replace with the verified resource**.
> Region: **OWNER DECISION**. Documentation/tutorial URL: **OWNER DECISION**.
> Maintenance contact and citation: **OWNER DECISION**.
> Release version, measured public bytes/rows and verification receipt:
> **OWNER — insert measurements from the final full release, not the subset**.
>
> Validation to report after execution: registry schema/CI result, anonymous S3
> reads, `_SUCCESS` and listed checksum verification, reader examples, and client
> pack validation against the merged writer.

Attach the completed [registry entry](release-registry.yaml). The accompanying
[release procedure](release-procedure.md) defines migration, staging and publication.
The implementation proof was a local 8,736,970-byte subset; it is not an already
public world release and is not evidence of cloud upload throughput or real pack
sizes. Fill those fields only after the owner executes and measures them.
