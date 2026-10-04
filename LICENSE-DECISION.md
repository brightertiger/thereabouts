# Licences

**Code:** MIT, decided by the owner on 2026-10-04; the text is in [LICENSE](LICENSE).
Python (`pyproject.toml`), npm (`clients/node/package.json`) and every Cargo crate
(`core/Cargo.toml` workspace package) declare it. MIT has no express patent-grant
clause; retain the copyright and permission notices in redistributions.

**Data:** the release dataset declares ODbL 1.0. Its DATA_LICENSES.md and
`manifest.sources` retain per-source licences, attribution, URLs and pins. The
database obligations and source-specific notices apply regardless of the code
licence; distributing code under MIT does not relicense the data. Review the
assembled release notices and source restrictions before redistributing any
dataset or pack.

**Decided 2026-10-04:** the `subdivisions` table is sourced from GeoNames
administrative codes (CC BY 4.0) only; the LGPL-2.1 iso-codes (pycountry) input
was removed so that no LGPL rows remain inside the ODbL database.

Third-party dependency licences for the Rust, Python and npm distributions are
unchanged by this choice; CI environments and registry trusted publishers are
configured by the owner before any publication.
