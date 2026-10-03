//! Portable batch, presentation and exit policy shared by native and WASM hosts.
#![cfg_attr(test, allow(clippy::unwrap_used))]
pub mod batch;
mod batch_spool;
pub mod directory;
pub mod error;
pub mod grammar;
pub mod io;
pub mod lease;
mod object;
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
