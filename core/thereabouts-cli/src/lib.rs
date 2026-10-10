//! Native command IO and persistent installation state.
#![cfg_attr(test, allow(clippy::unwrap_used))]
mod archive;
pub use thereabouts_cli_core::{error, render};
pub mod index;
pub mod install;
pub mod io;
pub mod store;
pub mod transfer;

mod args;
mod batch;
mod data;
mod dataset;
mod http;
mod lease;
mod query;
mod read_timeout;
mod runner;
pub use runner::run;
