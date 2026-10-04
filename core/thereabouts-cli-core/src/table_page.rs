//! Measure a complete table page with bounded memory and host-owned temporary storage.
use crate::{
    error::{Error, Result},
    io::{Io, Temporary},
    table::Layout,
};
use serde_json::Value;
use std::io::{BufRead, BufReader, SeekFrom};
use unicode_width::UnicodeWidthChar;

pub(crate) struct Page {
    columns: Vec<String>,
    layout: Layout,
    spool: Box<dyn Temporary>,
}
impl Page {
    pub fn new(columns: Vec<String>, io: &mut dyn Io) -> Result<Self> {
        if columns
            .iter()
            .any(|k| k.strip_prefix("thereabouts_").unwrap_or(k) == "evidence")
        {
            return Err(Error::Usage(
                "Evidence requires --json --evidence, not a table".into(),
            ));
        }
        Ok(Self {
            layout: Layout::new(&columns),
            columns,
            spool: io.temporary()?,
        })
    }
    pub fn push(&mut self, value: &Value) -> Result<()> {
        self.layout.observe(&self.columns, value);
        let mut value = value.clone();
        if let Some(fields) = value.as_object_mut() {
            for (key, field) in fields {
                let name = key.strip_prefix("thereabouts_").unwrap_or(key);
                if name == "query" || name.starts_with("query.") {
                    // Coordinate provenance is already display-ready. Spool its
                    // text so replay cannot round exact bounds through JSON's
                    // decimal-to-f64 parser a second time (notably on wasm32).
                    *field = Value::String(crate::table::summary(key, field));
                }
            }
        }
        self.spool
            .write_all(serde_json::to_string(&value)?.as_bytes())?;
        self.spool.write_all(b"\n")?;
        Ok(())
    }
    pub fn finish(mut self, io: &mut dyn Io) -> Result<()> {
        let terminal = io.terminal_columns();
        self.layout.fit(terminal)?;
        self.spool.flush()?;
        self.spool.seek(SeekFrom::Start(0))?;
        io.stdout(&self.layout.header(&self.columns))?;
        let mut reader = BufReader::new(self.spool);
        let mut line = String::new();
        while reader.read_line(&mut line)? != 0 {
            let value: Value = serde_json::from_str(&line)?;
            io.stdout(&self.layout.row(&self.columns, &value, false))?;
            if let Some(hint) = value
                .get("hint")
                .or_else(|| value.get("thereabouts_hint"))
                .and_then(Value::as_str)
            {
                write_hint(hint, terminal, io)?;
            }
            if let Some(candidates) = value
                .get("candidates")
                .or_else(|| value.get("thereabouts_candidates"))
                .and_then(Value::as_array)
            {
                for candidate in candidates {
                    let candidate = if value.get("thereabouts_status").is_some() {
                        Value::Object(
                            candidate
                                .as_object()
                                .into_iter()
                                .flatten()
                                .map(|(k, v)| (format!("thereabouts_{k}"), v.clone()))
                                .collect(),
                        )
                    } else {
                        candidate.clone()
                    };
                    io.stdout(&self.layout.row(&self.columns, &candidate, true))?;
                }
            }
            line.clear();
        }
        Ok(())
    }
}
fn write_hint(hint: &str, terminal: usize, io: &mut dyn Io) -> Result<()> {
    let available = terminal.saturating_sub(2).max(1);
    let mut line = String::from("  ");
    let mut used = 0;
    for c in "hint: ".chars().chain(hint.chars()) {
        let c = if c.is_control() { ' ' } else { c };
        let width = c.width().unwrap_or(0);
        if used + width > available {
            io.stdout(&format!("{line}\n"))?;
            line = "  ".into();
            used = 0;
        }
        line.push(c);
        used += width;
    }
    io.stdout(&format!("{line}\n"))?;
    Ok(())
}
