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
    #[error("{0}")]
    /// The process ran out of file descriptors; this is not damage to the pack.
    ResourceLimit(String),
    #[error(transparent)]
    /// An inventoried pack file could not be read.
    Io(std::io::Error),
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
            Self::ResourceLimit(_) => "resource_limit",
            _ => "corrupt_pack",
        }
    }
}
impl From<std::io::Error> for Error {
    fn from(error: std::io::Error) -> Self {
        if is_file_limit(&error) {
            Self::ResourceLimit(file_limit(&error))
        } else {
            Self::Io(error)
        }
    }
}
/// EMFILE/ENFILE (ERROR_TOO_MANY_OPEN_FILES on Windows): the process or system fd table is full.
#[must_use]
pub fn is_file_limit(error: &std::io::Error) -> bool {
    #[cfg(windows)]
    const CODES: [i32; 1] = [4];
    #[cfg(not(windows))]
    const CODES: [i32; 2] = [23, 24];
    error
        .raw_os_error()
        .is_some_and(|code| CODES.contains(&code))
}
/// One diagnostic for every host: name the limit, never suggest reinstalling data.
#[must_use]
pub fn file_limit(detail: &impl std::fmt::Display) -> String {
    format!("Too many open files ({detail}); raise the process open-file limit (ulimit -n)")
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
    #[test]
    #[cfg(not(windows))]
    fn descriptor_exhaustion_is_a_resource_limit_not_corruption() {
        for code in [23, 24] {
            let error = Error::from(std::io::Error::from_raw_os_error(code));
            assert_eq!(error.code(), "resource_limit");
            assert!(error.to_string().contains("ulimit -n"));
        }
        let missing = Error::from(std::io::Error::from(std::io::ErrorKind::NotFound));
        assert_eq!(missing.code(), "corrupt_pack");
    }
}
