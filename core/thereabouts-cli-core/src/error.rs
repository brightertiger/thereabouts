//! Command failures map to stable process exit codes.
use thiserror::Error;

/// Failures outside ordinary lookup results.
#[derive(Debug, Error)]
pub enum Error {
    /// Invalid flags, unsupported input shape or declined confirmation.
    #[error("{0}")]
    Usage(String),
    /// Discovery never installs implicitly.
    #[error("thereabouts data install {0}")]
    Missing(String),
    /// An existing installation is unusable.
    #[error(transparent)]
    Pack(#[from] thereabouts_core::Error),
    /// Store and transfer integrity failure.
    #[error("{0}")]
    Integrity(String),
    /// IO failure during an explicit command.
    #[error(transparent)]
    Io(std::io::Error),
    /// Malformed store or release metadata.
    #[error(transparent)]
    Json(#[from] serde_json::Error),
}
impl Error {
    /// Preserve partial downloads and give the same retry instruction for reset, EOF or stall.
    pub fn download_interrupted(detail: impl std::fmt::Display) -> Self {
        Self::Usage(format!(
            "Download interrupted; run the same data install again to resume: {detail}"
        ))
    }

    /// Add repair instructions while preserving missing, usage and incompatibility codes.
    #[must_use]
    pub fn at_pack(self, path: &std::path::Path, family: &str) -> Self {
        if matches!(
            self,
            Self::Usage(_)
                | Self::Missing(_)
                | Self::Io(_)
                | Self::Pack(thereabouts_core::Error::ResourceLimit(_))
        ) {
            return self;
        }
        let message = format!(
            "Unusable {family} pack at {}: {self}\nthereabouts data verify --full\nthereabouts data remove {family} --yes && thereabouts data install {family}",
            path.display()
        );
        if matches!(self, Self::Pack(thereabouts_core::Error::Incompatible(_))) {
            Self::Pack(thereabouts_core::Error::Incompatible(message))
        } else {
            Self::Integrity(message)
        }
    }
    /// Status reserved by the public command grammar.
    #[must_use]
    pub const fn exit_code(&self) -> i32 {
        match self {
            Self::Usage(_) | Self::Io(_) => 2,
            Self::Missing(_) => 3,
            Self::Pack(thereabouts_core::Error::ResourceLimit(_)) => 6,
            _ => 4,
        }
    }
}
/// Native command operation result.
pub type Result<T> = std::result::Result<T, Error>;

impl From<std::io::Error> for Error {
    fn from(error: std::io::Error) -> Self {
        if error.kind() == std::io::ErrorKind::StorageFull {
            Self::Usage("Not enough disk space to finish the operation".into())
        } else if thereabouts_core::error::is_file_limit(&error) {
            Self::Pack(thereabouts_core::Error::ResourceLimit(
                thereabouts_core::error::file_limit(&error),
            ))
        } else {
            Self::Io(error)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    #[cfg(not(windows))]
    fn resource_limits_keep_their_own_exit_code_and_advice() {
        let error = Error::from(std::io::Error::from_raw_os_error(24));
        assert_eq!(error.exit_code(), 6);
        let error = error.at_pack(std::path::Path::new("/store/core"), "core");
        assert_eq!(error.exit_code(), 6);
        assert!(!error.to_string().contains("verify --full"));
        let error = Error::from(thereabouts_core::Error::from(
            std::io::Error::from_raw_os_error(23),
        ));
        assert_eq!(
            error.at_pack(std::path::Path::new("x"), "core").exit_code(),
            6
        );
    }
}
