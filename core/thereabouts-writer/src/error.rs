//! Export failures are separate from the portable reader's error domain.
use thiserror::Error;

/// A dataset input, staging or encoding failure.
#[derive(Debug, Error)]
pub enum Error {
    #[error("{0}")]
    /// Dataset fields, policy, options or staging state are invalid.
    Input(String),
    #[error(transparent)]
    /// A shared encoder or verifier rejected the generated or existing pack.
    Core(#[from] thereabouts_core::Error),
    #[error(transparent)]
    /// Source, staging or output filesystem access failed.
    Io(#[from] std::io::Error),
    #[error(transparent)]
    /// Dataset or options JSON is invalid.
    Json(#[from] serde_json::Error),
    #[error(transparent)]
    /// A required input table could not be decoded.
    Parquet(#[from] parquet::errors::ParquetError),
    #[error(transparent)]
    /// A typed dataset column could not be interpreted.
    Arrow(#[from] arrow_schema::ArrowError),
    #[error(transparent)]
    /// The bounded staging index could not complete an operation.
    Sql(#[from] rusqlite::Error),
}
impl Error {
    /// Stable export boundary code; no writer failure masquerades as a reader failure.
    #[must_use]
    pub fn code(&self) -> &'static str {
        match self {
            Self::Input(_) | Self::Json(_) | Self::Parquet(_) | Self::Arrow(_) => {
                "writer_input_error"
            }
            Self::Core(_) | Self::Io(_) | Self::Sql(_) => "writer_error",
        }
    }
}
/// Result of a dataset export operation.
pub type Result<T> = std::result::Result<T, Error>;
pub(crate) fn ensure(valid: bool, message: &str) -> Result<()> {
    if valid {
        Ok(())
    } else {
        Err(Error::Input(message.into()))
    }
}
