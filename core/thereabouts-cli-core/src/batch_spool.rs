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
) -> Result<(Box<dyn crate::io::Temporary>, Vec<String>, bool)> {
    let mut frame_rows = false;
    let mut seen = BTreeSet::new();
    let mut fields = Vec::new();
    let mut bytes = 0usize;
    let mut line = first.to_owned();
    loop {
        match serde_json::from_str::<crate::object::Object>(&line) {
            Ok(object) => {
                frame_rows |= object.values.contains_key("frame");
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
    Ok((file, fields, frame_rows))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Cursor, Read, Write};

    #[test]
    fn late_frame_after_malformed_and_legacy_rows_reserves_query() {
        let mut input = Cursor::new(b"{\"lat\":0,\"lon\":0}\n{\"frame\":\"ecef\",\"x\":1}\n");
        let (mut spool, fields, query) =
            collect("bad\n", Box::new(Cursor::new(Vec::new())), |line| {
                std::io::BufRead::read_line(&mut input, line)
            })
            .unwrap();
        assert!(query);
        assert_eq!(fields, ["input", "lat", "lon", "frame", "x"]);
        let mut text = String::new();
        spool.read_to_string(&mut text).unwrap();
        assert_eq!(
            text,
            "bad\n{\"lat\":0,\"lon\":0}\n{\"frame\":\"ecef\",\"x\":1}\n"
        );
        let (_, _, query) = collect(
            "{\"lat\":0,\"lon\":0}\n",
            Box::new(Cursor::new(Vec::new())),
            |_| Ok(0),
        )
        .unwrap();
        assert!(!query);
    }
    #[test]
    fn column_and_name_byte_budgets_remain_bounded() {
        for object in [
            serde_json::Value::Object(
                (0..=MAX_FIELDS)
                    .map(|i| (format!("c{i}"), serde_json::Value::Null))
                    .collect(),
            ),
            serde_json::json!({"x".repeat(MAX_FIELD_BYTES + 1): 0}),
        ] {
            let error = collect(
                &object.to_string(),
                Box::new(Cursor::new(Vec::new())),
                |_| Ok(0),
            )
            .err()
            .unwrap();
            assert!(error.to_string().contains("column limit"));
        }
    }
    struct FullDisk;
    impl Read for FullDisk {
        fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
            Ok(0)
        }
    }
    impl io::Seek for FullDisk {
        fn seek(&mut self, _: SeekFrom) -> io::Result<u64> {
            Ok(0)
        }
    }
    impl Write for FullDisk {
        fn write(&mut self, _: &[u8]) -> io::Result<usize> {
            Err(io::Error::from(io::ErrorKind::StorageFull))
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    #[test]
    fn spool_disk_failure_is_an_error() {
        let error = collect("{}\n", Box::new(FullDisk), |_| Ok(0))
            .err()
            .unwrap();
        assert_eq!(error.exit_code(), 2);
        assert!(error.to_string().contains("Not enough disk"));
    }
}
