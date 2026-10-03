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
    /// Status reserved by the public command grammar.
    #[must_use]
    pub const fn exit_code(&self) -> i32 {
        match self {
            Self::Usage(_) => 2,
            Self::Missing(_) => 3,
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
        } else {
            Self::Io(error)
        }
    }
}
