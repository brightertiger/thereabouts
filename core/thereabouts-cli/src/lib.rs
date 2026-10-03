//! Native command IO and persistent installation state.
#![cfg_attr(test, allow(clippy::unwrap_used))]
mod archive;
pub mod error;
pub mod index;
pub mod install;
pub mod io;
pub mod store;
pub mod transfer;
