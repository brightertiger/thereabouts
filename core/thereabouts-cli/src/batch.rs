//! Filesystem adapter for the shared streaming batch policy.
use crate::{
    args::{Format, Global, Reverse},
    error::{Error, Result},
    io::Io,
};
use std::{
    fs::File,
    io::{BufRead, BufReader},
};
use thereabouts_core::format::Pack;

pub(crate) fn run(
    file: &str,
    reverse: &Reverse,
    pack: &Pack,
    coordinates: &thereabouts_cli_core::coords::Options,
    options: &Global,
    format: Format,
    io: &mut dyn Io,
) -> Result<i32> {
    let input: Option<Box<dyn BufRead>> = if file == "-" {
        None
    } else {
        Some(Box::new(BufReader::new(File::open(file).map_err(|e| {
            Error::Usage(format!("Cannot read input file {file}: {e}"))
        })?)))
    };
    thereabouts_cli_core::batch::run(
        pack,
        &thereabouts_cli_core::batch::Options {
            filename: file.into(),
            coordinates: coordinates.clone(),
            lat_col: reverse.lat_col.clone(),
            lon_col: reverse.lon_col.clone(),
            evidence: options.evidence,
            strict: options.strict,
            fields: options.fields.clone(),
            format,
        },
        input,
        io,
    )
}
