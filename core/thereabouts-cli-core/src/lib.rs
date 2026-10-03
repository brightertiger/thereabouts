//! Portable batch, presentation and exit policy shared by native and WASM hosts.
#![cfg_attr(test, allow(clippy::unwrap_used))]
pub mod batch;
mod batch_spool;
pub mod error;
pub mod io;
pub mod render;
mod table;
use serde::{Deserialize, Serialize};
use thereabouts_core::result::Status;

/// Explicit output encoding; automatic selection belongs to the host's TTY policy.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Format {
    /// Bounded human place summaries.
    Table,
    /// One pretty object, or one streamed results array for a batch.
    Json,
    /// One complete JSON object per input row.
    Ndjson,
    /// Ordered input columns followed by public result columns.
    Csv,
}
impl std::str::FromStr for Format {
    type Err = error::Error;
    fn from_str(value: &str) -> error::Result<Self> {
        match value {
            "table" => Ok(Self::Table),
            "json" => Ok(Self::Json),
            "ndjson" => Ok(Self::Ndjson),
            "csv" => Ok(Self::Csv),
            _ => Err(error::Error::Usage(
                "Use --format table|json|ndjson|csv".into(),
            )),
        }
    }
}
/// Scalar process status, independent of language and output encoding.
#[must_use]
pub const fn exit(status: Status, strict: bool) -> i32 {
    match status {
        Status::InvalidInput | Status::UnsupportedGranularity => 2,
        Status::NotFound if strict => 1,
        _ => 0,
    }
}

/// Stable loopback coordination address for hosts without OS file-lock APIs.
/// The high ephemeral range avoids privileged ports. A collision fails closed.
#[must_use]
pub fn lock_port(canonical_root: &str) -> u16 {
    use sha2::{Digest, Sha256};
    let normalized = canonical_root
        .strip_prefix(r"\\?\")
        .unwrap_or(canonical_root)
        .replace('\\', "/");
    let normalized = if normalized.as_bytes().get(1) == Some(&b':') {
        normalized.to_lowercase()
    } else {
        normalized
    };
    let hash = Sha256::digest(normalized.as_bytes());
    let prefix = hash
        .as_slice()
        .get(..2)
        .and_then(|v| <[u8; 2]>::try_from(v).ok())
        .unwrap_or([0; 2]);
    49152 + (u16::from_be_bytes(prefix) & 16383)
}

#[cfg(test)]
mod tests {
    #[test]
    fn store_lock_identity_is_stable_across_windows_canonical_spelling() {
        assert_eq!(
            super::lock_port(r"\\?\C:\Users\Test\Store"),
            super::lock_port("c:/users/test/store")
        );
        assert_ne!(
            super::lock_port("/store/one"),
            super::lock_port("/store/two")
        );
    }
}
