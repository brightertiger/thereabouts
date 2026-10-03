//! Offline pack decoding and dataset export, shared by all client surfaces.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
pub mod error;
pub mod format;
pub mod result;
pub mod reverse;
pub use error::{Error, Result};
