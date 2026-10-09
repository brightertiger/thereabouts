//! Release discovery is explicit and independent of installed lookup data.
use crate::{
    error::{Error, Result},
    store,
};
use serde::{Deserialize, Serialize};
use std::{cmp::Ordering, collections::BTreeMap};
use thereabouts_cli_core::transport::{INDEX_FORMAT, MAX_ARCHIVE_BYTES, MAX_UNPACKED_BYTES};

/// One immutable zstd-compressed ustar archive holding manifest.json and its files.
/// Unknown fields are ignored so the index can grow without breaking clients.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct ReleasePack {
    /// Absolute URL or source-relative archive path.
    pub url: String,
    /// Exact compressed archive length, used for bounded download and resume.
    pub size: u64,
    /// Lowercase SHA-256 of the compressed archive.
    pub sha256: String,
    /// Exact decompressed ustar length; extraction stops beyond it.
    pub unpacked_size: u64,
    /// Required minor format for this family.
    pub format_minor: u16,
}
/// A coordinated dataset release.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Dataset {
    /// Available family archives.
    pub packs: BTreeMap<String, ReleasePack>,
}
/// Public release index version 3.
#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Index {
    /// Release index format.
    pub format: u32,
    /// Dataset versions, independent of client version.
    pub datasets: BTreeMap<String, Dataset>,
}
impl Index {
    /// Validate index identities, paths and advertised bounds before selection.
    pub fn validate(&self) -> Result<()> {
        if self.format != INDEX_FORMAT {
            return Err(thereabouts_core::Error::Incompatible(format!(
                "Requires release index format {INDEX_FORMAT}, found {}; use a matching client",
                self.format
            ))
            .into());
        }
        for (version, dataset) in &self.datasets {
            store::component(version)?;
            for (name, pack) in &dataset.packs {
                store::component(name)?;
                if !(1..=MAX_ARCHIVE_BYTES).contains(&pack.size)
                    || !(1..=MAX_UNPACKED_BYTES).contains(&pack.unpacked_size)
                    || pack.url.is_empty()
                    || pack.sha256.len() != 64
                    || !pack
                        .sha256
                        .bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
                {
                    return Err(Error::Integrity("Invalid release archive identity".into()));
                }
            }
        }
        Ok(())
    }
    /// Newest release for which all requested families are supported.
    pub fn select(&self, requested: &[String], version: Option<&str>) -> Result<(&str, &Dataset)> {
        self.validate()?;
        for name in requested {
            store::family(name)?;
        }
        let supported = |dataset: &Dataset| {
            requested
                .iter()
                .all(|name| dataset.packs.get(name).is_some_and(|p| p.format_minor == 2))
        };
        if let Some(version) = version {
            return self
                .datasets
                .get_key_value(version)
                .filter(|(_, d)| supported(d))
                .map(|(v, d)| (v.as_str(), d))
                .ok_or_else(|| {
                    Error::Integrity("Requested dataset is unavailable or incompatible".into())
                });
        }
        self.datasets
            .iter()
            .filter(|(_, d)| supported(d))
            .max_by(|(a, _), (b, _)| compare_versions(a, b))
            .map(|(v, d)| (v.as_str(), d))
            .ok_or_else(|| Error::Integrity("No compatible dataset release".into()))
    }
}
/// Compare dotted numeric releases naturally, with byte-order text tie breaking.
pub(crate) fn compare_versions(a: &str, b: &str) -> Ordering {
    for (left, right) in a.split('.').zip(b.split('.')) {
        let order = match (left.parse::<u64>(), right.parse::<u64>()) {
            (Ok(l), Ok(r)) => l.cmp(&r),
            _ => left.cmp(right),
        };
        if order != Ordering::Equal {
            return order;
        }
    }
    a.split('.')
        .count()
        .cmp(&b.split('.').count())
        .then_with(|| a.cmp(b))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn newest_supported_release_uses_numeric_version_order() {
        let pack = |minor: u16| {
            serde_json::json!({"url":"core.tar.zst","size":1024,"sha256":"0".repeat(64),
                "unpacked_size":4096,"format_minor":minor})
        };
        let mut index: Index = serde_json::from_value(serde_json::json!({
            "format": 3,
            "datasets": {
                "2026.9": {"packs":{"core":pack(2)}},
                "2026.10": {"packs":{"core":pack(2)}},
                "2027.1": {"packs":{"core":pack(8)}}
            }
        }))
        .unwrap();
        let names = vec!["core".into()];
        assert_eq!(index.select(&names, None).unwrap().0, "2026.10");
        assert_eq!(index.select(&names, Some("2026.9")).unwrap().0, "2026.9");
        assert!(index.select(&names, Some("2027.1")).is_err());
        index.format = 2;
        assert!(
            index
                .validate()
                .unwrap_err()
                .to_string()
                .contains("format 3")
        );
    }
    #[test]
    #[allow(clippy::indexing_slicing)]
    fn unknown_fields_are_ignored_and_caps_are_enforced() {
        let index = |pack: serde_json::Value| {
            serde_json::from_value::<Index>(serde_json::json!({
                "format": 3, "latest": "2026.10", "signature": "x",
                "datasets": {"2026.10": {"published": "2026-10-09", "packs": {"core": pack}}}
            }))
            .unwrap()
        };
        let mut pack = serde_json::json!({"url":"2026.10/core.tar.zst","size":1,
            "sha256":"a".repeat(64),"unpacked_size":1,"format_minor":2,"mirrors":[]});
        index(pack.clone()).validate().unwrap();
        pack["size"] = (MAX_ARCHIVE_BYTES + 1).into();
        assert!(index(pack.clone()).validate().is_err());
        pack["size"] = 1.into();
        pack["unpacked_size"] = (MAX_UNPACKED_BYTES + 1).into();
        assert!(index(pack.clone()).validate().is_err());
        pack["unpacked_size"] = 0.into();
        assert!(index(pack).validate().is_err());
    }
}
