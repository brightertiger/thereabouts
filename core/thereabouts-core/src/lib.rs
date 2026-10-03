//! Offline pack decoding and dataset export, shared by all client surfaces.
pub mod error;
pub mod format;
pub mod result;
pub mod reverse;
pub use error::{Error, Result};
