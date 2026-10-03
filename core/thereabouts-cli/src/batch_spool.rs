//! Tabular NDJSON needs the union of input keys before emitting its header.
use crate::error::{Error, Result};
use serde_json::{Map, Value};
use std::{
    collections::BTreeSet,
    io::{self, Write},
};

/// Keep at most 4,096 distinct input columns and 1 MiB of names in memory.
/// Row contents are spooled to disk; no complete batch is retained in RAM.
const MAX_FIELDS: usize = 4096;
const MAX_FIELD_BYTES: usize = 1024 * 1024;
pub(crate) fn collect(
    first: &str,
    mut read: impl FnMut(&mut String) -> io::Result<usize>,
) -> Result<(tempfile::NamedTempFile, Vec<String>)> {
    let mut file = tempfile::NamedTempFile::new()?;
    let mut fields = BTreeSet::new();
    let mut bytes = 0usize;
    let mut line = first.to_owned();
    loop {
        match serde_json::from_str::<Map<String, Value>>(&line) {
            Ok(object) => {
                for (key, _) in object {
                    if fields.insert(key.clone()) {
                        bytes += key.len();
                    }
                }
            }
            Err(_) => {
                if fields.insert("input".into()) {
                    bytes += "input".len();
                }
            }
        }
        if fields.len() > MAX_FIELDS || bytes > MAX_FIELD_BYTES {
            return Err(Error::Usage(
                "Tabular input exceeds column limit; use NDJSON output".into(),
            ));
        }
        file.write_all(line.as_bytes())?;
        line.clear();
        if read(&mut line)? == 0 {
            break;
        }
    }
    file.flush()?;
    Ok((file, fields.into_iter().collect()))
}
