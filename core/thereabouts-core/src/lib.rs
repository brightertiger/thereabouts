//! Offline pack decoding and reverse lookup, shared by all client surfaces.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
pub mod coords;
pub mod error;
pub mod format;
pub mod result;
pub mod reverse;
pub use error::{Error, Result};

pub mod airports;
pub mod forward;
pub mod locode;
pub mod postal;

pub mod phone;

pub mod ip;

pub mod plates;
mod plates_geography;
mod plates_index;

pub mod geocode;
pub mod name_normalization;
mod name_query;

mod name_distance;
