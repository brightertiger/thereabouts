//! Release discovery is explicit and independent of installed lookup data.
use crate::{
    error::{Error, Result},
    store,
};
use serde::{Deserialize, Serialize};
use std::{cmp::Ordering, collections::BTreeMap};

/// Placeholder until the owner publishes a release service.
pub const DEFAULT_SOURCE: &str = "https://thereabouts-releases.invalid";
/// Archive and metadata sizes are checked before transfer or allocation.
pub const MAX_ARCHIVE_BYTES: u64 = 1024 * 1024 * 1024;

/// One immutable archive, containing manifest.json and its inventoried files.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleasePack {
    /// Absolute URL or source-relative archive filename.
    pub url: String,
    /// Exact archive length, used for bounded download and resume.
    pub bytes: u64,
    /// Lowercase archive SHA-256.
    pub sha256: String,
    /// Required minor format for this family.
    pub format_minor: u16,
}
/// A coordinated dataset release.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Dataset {
    /// Available family archives.
    pub packs: BTreeMap<String, ReleasePack>,
}
/// Public release index version 2.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Index {
    /// Index and pack major format.
    pub format: u32,
    /// Dataset versions, independent of client version.
    pub datasets: BTreeMap<String, Dataset>,
}
impl Index {
    /// Validate index identities, paths and advertised bounds before selection.
    pub fn validate(&self) -> Result<()> {
        if self.format != 2 {
            return Err(thereabouts_core::Error::Incompatible(
                "Requires release index format 2".into(),
            )
            .into());
        }
        for (version, dataset) in &self.datasets {
            store::component(version)?;
            for (name, pack) in &dataset.packs {
                store::component(name)?;
                if pack.bytes == 0
                    || pack.bytes > MAX_ARCHIVE_BYTES
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
        let mut index: Index = serde_json::from_value(serde_json::json!({
            "format": 2,
            "datasets": {
                "2026.9": {"packs":{"core":{"url":"core.tar","bytes":1024,"sha256":"0".repeat(64),"format_minor":2}}},
                "2026.10": {"packs":{"core":{"url":"core.tar","bytes":1024,"sha256":"0".repeat(64),"format_minor":2}}},
                "2027.1": {"packs":{"core":{"url":"core.tar","bytes":1024,"sha256":"0".repeat(64),"format_minor":8}}}
            }
        })).unwrap();
        let names = vec!["core".into()];
        assert_eq!(index.select(&names, None).unwrap().0, "2026.10");
        assert_eq!(index.select(&names, Some("2026.9")).unwrap().0, "2026.9");
        assert!(index.select(&names, Some("2027.1")).is_err());
        index.format = 3;
        assert!(index.validate().is_err());
    }
}
