//! Tabular NDJSON needs the union of input keys before emitting its header.
use crate::error::{Error, Result};
use std::{
    collections::BTreeSet,
    io::{self, SeekFrom},
};

/// Keep at most 4,096 distinct input columns and 1 MiB of names in memory.
/// Row contents are spooled to disk; no complete batch is retained in RAM.
const MAX_FIELDS: usize = 4096;
const MAX_FIELD_BYTES: usize = 1024 * 1024;
pub(crate) fn collect(
    first: &str,
    mut file: Box<dyn crate::io::Temporary>,
    mut read: impl FnMut(&mut String) -> io::Result<usize>,
) -> Result<(Box<dyn crate::io::Temporary>, Vec<String>)> {
    let mut seen = BTreeSet::new();
    let mut fields = Vec::new();
    let mut bytes = 0usize;
    let mut line = first.to_owned();
    loop {
        match serde_json::from_str::<crate::object::Object>(&line) {
            Ok(object) => {
                for key in object.keys {
                    if seen.insert(key.clone()) {
                        bytes += key.len();
                        fields.push(key);
                    }
                }
            }
            Err(_) => {
                if seen.insert("input".into()) {
                    fields.push("input".into());
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
    file.seek(SeekFrom::Start(0))?;
    Ok((file, fields))
}
