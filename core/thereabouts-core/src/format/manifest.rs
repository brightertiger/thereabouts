//! Pack identity and safe, explicitly inventoried artifacts.
use super::container::MAX_SHARD_BYTES;
use crate::{Error, Result, error::ensure};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
};

/// Artifact identity; ranges are validated from the binary directories.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Artifact {
    /// Portable relative artifact path; traversal and symlinks are rejected.
    pub path: String,
    /// Artifact role: cells, catalogue, metadata or notice.
    pub kind: String,
    /// Exact byte length checked before any payload allocation.
    pub size: u64,
    /// Lowercase SHA-256 checked by explicit full verification.
    pub sha256: String,
}
/// Writer accounting, independently reproducible from inventoried section lengths.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
pub struct Storage {
    /// Original observations, counting an airport once.
    pub source_rows: u64,
    /// Compressed query columns and hot strings, excluding evidence and container framing.
    pub query_compressed_bytes: u64,
    /// Separate compressed source, detail and provenance payloads.
    pub evidence_compressed_bytes: u64,
    /// All data artifacts, including FSTs, evidence, framing and directories.
    pub data_artifact_bytes: u64,
    /// Actual supporting catalogue bytes; not extrapolated per input row.
    pub catalogue_bytes: u64,
    /// Actual referenced metadata bytes; not extrapolated per input row.
    pub metadata_bytes: u64,
}
/// Required pack identity and source attribution, independent of build paths.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    /// Exact shared core catalogue identity; required for forward format 2.2.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub core_catalogue: Option<CoreCatalogue>,
    /// All families require minor two: shared geography and bounded catalogue reads.
    #[serde(default, skip_serializing_if = "zero")]
    pub format_minor: u16,
    /// Compressed forward dictionary schema, absent for spatial/name-only core.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub forward_columns: Option<super::compact::Schema>,
    /// Plate policy for columnar format/code assertions with cold provenance.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub plate_columns: Option<super::plates::Schema>,
    /// Physical writer accounting; checked independently by measurement tools.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub storage: Option<Storage>,
    /// Required schema identifier, thereabouts-pack-2.
    pub schema: String,
    /// Wire format integer; this reader accepts 2.
    pub format_version: u32,
    /// Pack family selects the required lookup indexes.
    pub family: String,
    /// Explicit dataset release identity, independent of library version.
    pub data_version: String,
    /// Unknown required bits cause incompatibility; currently zero.
    pub required_features: u32,
    /// Coordinate indexing resolution; currently eight.
    pub reference_resolution: u8,
    /// Spatial directory resolution; currently three.
    pub block_resolution: u8,
    /// Digest of the deterministic writer input identity.
    pub input_digest: String,
    /// Source manifest, encoding revision and export options used for identity.
    pub inputs: serde_json::Value,
    /// Published source descriptions retained without inference.
    pub sources: serde_json::Value,
    /// Human-readable attribution accompanying the license artifacts.
    pub attribution: String,
    /// Ordered artifact inventory; order defines global catalogue references.
    pub files: Vec<Artifact>,
    /// Ordered code normalization operations; required for forward code packs.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub normalization: Vec<String>,
    /// Canonical-city spelling policy; required whenever name indexes are present.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name_normalization: Option<crate::name_normalization::Policy>,
    /// Exclusive lower bound for distant-nearest, in metres.
    pub distant_over_m: u32,
    /// Inclusive upper bound for distant-nearest, in metres.
    pub cutoff_m: u32,
}
#[allow(clippy::trivially_copy_pass_by_ref)] // serde's skip predicate takes a field reference.
fn zero(value: &u16) -> bool {
    *value == 0
}
/// Hash a file in bounded chunks; never load Parquet just to fingerprint it.
pub fn digest(path: &Path) -> Result<String> {
    super::reader::Reader::native(Path::new("")).digest(path)
}
/// Reject path traversal and symlinks, including symlinked parent directories.
pub fn artifact_path(root: &Path, name: &str) -> Result<PathBuf> {
    ensure(
        !name.is_empty() && !name.contains(['\\', ':']) && !name.starts_with('/'),
        "Unsafe artifact path",
    )?;
    let mut path = root.to_path_buf();
    for part in name.split('/') {
        ensure(!matches!(part, "" | "." | ".."), "Unsafe artifact path")?;
        path.push(part);
        #[cfg(not(target_arch = "wasm32"))]
        if let Ok(metadata) = std::fs::symlink_metadata(&path) {
            ensure(!metadata.file_type().is_symlink(), "Symlink artifact")?;
        }
    }
    Ok(path)
}
/// Read compatible metadata, limiting allocations before JSON parsing.
pub fn read(root: &Path) -> Result<Manifest> {
    if !root.exists() {
        return Err(Error::PackNotFound(root.to_owned()));
    }
    read_with(&super::reader::Reader::native(root))
}
/// Admit manifest and artifact sizes through a host-provided stable file source.
pub fn read_with(root: &super::reader::Reader<'_>) -> Result<Manifest> {
    let path = artifact_path(root, "manifest.json")?;
    ensure(
        root.open(&path)?.size() <= 16 * 1024 * 1024,
        "Oversized manifest",
    )?;
    let value: serde_json::Value = serde_json::from_slice(&root.read(&path)?)?;
    if value
        .get("format_version")
        .and_then(serde_json::Value::as_u64)
        != Some(2)
        || !matches!(
            value.get("family").and_then(serde_json::Value::as_str),
            Some("core" | "postal" | "airports" | "locode" | "phone" | "ip" | "plates")
        )
        || value.get("schema").and_then(serde_json::Value::as_str) != Some("thereabouts-pack-2")
    {
        return Err(Error::Incompatible(
            "Requires a supported format-2 pack".into(),
        ));
    }
    let m: Manifest = serde_json::from_value(value)?;
    compatible_minor(&m)?;
    validate_pin(&m)?;
    if m.required_features != 0 || m.reference_resolution != 8 || m.block_resolution != 3 {
        return Err(Error::Incompatible(
            "Unsupported pack features or resolutions".into(),
        ));
    }
    ensure(
        !m.data_version.is_empty() && m.distant_over_m <= m.cutoff_m,
        "Invalid dataset identity or nearest policy",
    )?;
    if m.family == "postal"
        && m.normalization != ["strip_ascii", "upper_ascii", "remove_ascii_spaces"]
    {
        return Err(Error::Incompatible(
            "Unsupported postal normalization".into(),
        ));
    }
    if matches!(m.family.as_str(), "airports" | "locode")
        && m.normalization != ["strip_ascii", "upper_ascii"]
    {
        return Err(Error::Incompatible(
            "Unsupported airport normalization".into(),
        ));
    }
    if m.family == "phone" && m.normalization != ["e164_plus", "strip_phone_presentation"] {
        return Err(Error::Incompatible(
            "Unsupported phone normalization".into(),
        ));
    }
    if m.family == "ip" && m.normalization != ["ip_literal"] {
        return Err(Error::Incompatible("Unsupported IP normalization".into()));
    }
    if m.family == "plates"
        && m.normalization != ["nfc", "upper_ascii", "collapse_python_whitespace"]
    {
        return Err(Error::Incompatible(
            "Unsupported plate normalization".into(),
        ));
    }
    if let Some(policy) = &m.name_normalization {
        policy.validate()?;
    }
    ensure(
        m.files.iter().any(|f| f.kind == "names") == m.name_normalization.is_some(),
        "Name policy/index inventory disagree",
    )?;
    let mut names = BTreeSet::new();
    for f in &m.files {
        ensure(
            f.path != "manifest.json" && names.insert(&f.path) && f.size <= MAX_SHARD_BYTES as u64,
            "Invalid artifact inventory",
        )?;
        ensure(
            f.sha256.len() == 64
                && f.sha256
                    .bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)),
            "Invalid checksum",
        )?;
        let path = artifact_path(root, &f.path)?;
        ensure(root.open(&path)?.size() == f.size, "Artifact size mismatch")?;
    }
    Ok(m)
}
/// Verify every checksum, including notices and metadata tables.
pub fn verify(root: &Path, m: &Manifest) -> Result<()> {
    verify_with(&super::reader::Reader::native(root), m)
}
/// Verify digests through the same handles used by admission and later reads.
pub fn verify_with(root: &super::reader::Reader<'_>, m: &Manifest) -> Result<()> {
    for f in &m.files {
        ensure(
            root.digest(&artifact_path(root, &f.path)?)? == f.sha256,
            "Shard checksum mismatch",
        )?;
    }
    Ok(())
}

fn compatible_minor(m: &Manifest) -> Result<()> {
    if m.family == "core"
        && (m.format_minor != 2 || m.forward_columns.is_some() || m.plate_columns.is_some())
        || m.family != "core"
            && m.files
                .iter()
                .any(|f| matches!(f.kind.as_str(), "exact" | "trie" | "intervals" | "plates"))
        || m.forward_columns.is_some() && m.plate_columns.is_some()
    {
        return Err(Error::Incompatible(
            "Unsupported family/container revision".into(),
        ));
    }
    if m.family != "core"
        && (m.format_minor != 2
            || m.core_catalogue.is_none()
            || m.files.iter().any(|f| f.kind == "catalogue")
            || if m.family == "plates" {
                m.plate_columns.is_none()
            } else {
                m.forward_columns.is_none()
            })
    {
        return Err(Error::Incompatible(
            "Forward packs require format 2.2; rebuild this pack".into(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn traversal_and_symlinks_are_rejected() {
        let temp = tempfile::tempdir().unwrap();
        for name in ["../secret", "/absolute", "a//b", "a\\b", "a:b", ".", ""] {
            assert!(artifact_path(temp.path(), name).is_err());
        }
        assert!(artifact_path(temp.path(), "cells/one.bin").is_ok());
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink("missing", temp.path().join("link")).unwrap();
            assert!(artifact_path(temp.path(), "link").is_err());
        }
    }
}

/// A forward pack's ordinal namespace, independent of installation paths.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct CoreCatalogue {
    /// Dataset release; must equal the forward release.
    pub data_version: String,
    /// SHA-256 of the ordered catalogue inventory, including sizes and content hashes.
    pub sha256: String,
    /// Maximum one-based place ordinal; zero always means absent.
    pub place_count: u32,
}
/// Fingerprint the catalogue namespace without rereading catalogue payloads.
/// SHA-256 covers JSON arrays [path,size,sha256] in manifest inventory order.
pub fn catalogue_digest(manifest: &Manifest) -> Result<String> {
    let inventory = manifest
        .files
        .iter()
        .filter(|f| f.kind == "catalogue")
        .map(|f| (&f.path, f.size, &f.sha256))
        .collect::<Vec<_>>();
    Ok(format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&inventory)?)
    ))
}

fn validate_pin(m: &Manifest) -> Result<()> {
    if let Some(pin) = &m.core_catalogue {
        ensure(
            m.family != "core"
                && pin.data_version == m.data_version
                && pin.sha256.len() == 64
                && pin
                    .sha256
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
            "Invalid core catalogue pin",
        )?;
    }
    Ok(())
}
