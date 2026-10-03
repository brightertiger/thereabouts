//! Export failures are separate from the portable reader's error domain.
use thiserror::Error;

/// A dataset input, staging or encoding failure.
#[derive(Debug, Error)]
pub enum Error {
    #[error("{0}")]
    Input(String),
    #[error("{0}")]
    Incompatible(String),
    #[error(transparent)]
    Core(#[from] thereabouts_core::Error),
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
    /// Stable boundary code; reader failures retain their original code.
    #[must_use]
    pub fn code(&self) -> &'static str {
        match self {
            Self::Core(error) => error.code(),
            Self::Incompatible(_) => "incompatible_data",
            Self::Input(_) => "invalid_input",
            _ => "corrupt_pack",
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
