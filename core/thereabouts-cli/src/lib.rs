//! Native command IO and persistent installation state.
#![cfg_attr(test, allow(clippy::unwrap_used))]
mod archive;
pub mod error;
pub mod index;
pub mod install;
pub mod io;
pub mod store;
pub mod transfer;

mod args;
mod batch;
mod batch_spool;
mod data;
mod http;
mod query;
mod render;
mod runner;
pub use runner::run;
