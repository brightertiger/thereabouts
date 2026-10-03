//! Stable failure codes; misses remain ordinary lookup results.
use thiserror::Error;

/// Failures that prevent interpreting a pack or completing an operation.
#[derive(Debug, Error)]
pub enum Error {
    #[error("thereabouts data install core")]
    Missing,
    #[error("{0}")]
    Incompatible(String),
    #[error("{0}")]
    Corrupt(String),
    #[error("Geocoder is closed")]
    Closed,
    #[error("{0}")]
    Input(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    Parquet(#[from] parquet::errors::ParquetError),
    #[error(transparent)]
    Arrow(#[from] arrow_schema::ArrowError),
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
}
impl Error {
    /// Machine-readable code, independent of the diagnostic text.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Missing => "data_not_installed",
            Self::Incompatible(_) => "incompatible_data",
            Self::Closed => "closed_geocoder",
            Self::Input(_) => "invalid_input",
            _ => "corrupt_pack",
        }
    }
}
/// Core operations use one error domain across language bindings.
pub type Result<T> = std::result::Result<T, Error>;
/// Reject invalid bytes with a stable integrity error.
pub fn ensure(valid: bool, message: &str) -> Result<()> {
    if valid {
        Ok(())
    } else {
        Err(Error::Corrupt(message.into()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stable_missing_data_message() {
        assert_eq!(Error::Missing.to_string(), "thereabouts data install core");
        assert_eq!(Error::Missing.code(), "data_not_installed");
        assert_eq!(Error::Closed.code(), "closed_geocoder");
    }
}
