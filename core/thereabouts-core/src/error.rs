//! Stable failure codes; misses remain ordinary lookup results.
use thiserror::Error;

/// Failures that prevent interpreting a pack or completing an operation.
#[derive(Debug, Error)]
pub enum Error {
    #[error("thereabouts data install core")]
    /// No pack was discovered in the store; bindings present the install command.
    Missing,
    #[error("Pack not found: {0}")]
    /// The explicitly selected directory does not exist.
    PackNotFound(std::path::PathBuf),
    #[error("{0}")]
    /// The pack requires another format, family or required feature.
    Incompatible(String),
    #[error("{0}")]
    /// Wire structure, reference or checksum validation failed.
    Corrupt(String),
    #[error("Geocoder is closed")]
    /// A binding handle has been explicitly closed.
    Closed,
    #[error("{0}")]
    /// An internal codec caller supplied an invalid encoding value.
    Input(String),
    #[error(transparent)]
    /// An inventoried pack file could not be read.
    Io(#[from] std::io::Error),
    #[error(transparent)]
    /// Pack JSON could not be parsed without losing its structure.
    Json(#[from] serde_json::Error),
}
impl Error {
    /// Machine-readable code, independent of the diagnostic text.
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::Missing => "data_not_installed",
            Self::PackNotFound(_) => "pack_not_found",
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
