//! Output never changes result semantics, and batch rendering retains one row.
use crate::{
    Format,
    error::{Error, Result},
    io::Io,
};
use serde_json::{Map, Value};

/// Supported dotted paths, ordered by their public parent fields.
pub const FIELDS: &[&str] = &[
    "status",
    "kind",
    "match",
    "country",
    "country.code",
    "country.code3",
    "country.name",
    "state",
    "state.code",
    "state.name",
    "city",
    "city.id",
    "city.name",
    "city.name_en",
    "city.kind",
    "city.population",
    "city.point",
    "city.point.lat",
    "city.point.lon",
    "timezone",
    "point",
    "point.lat",
    "point.lon",
    "cell",
    "distance_band",
    "distance_band.greater_than_km",
    "distance_band.at_most_km",
    "candidates",
    "rank_basis",
    "hint",
    "evidence",
];
/// Validate an explicit ordered result-field selection.
pub fn fields(value: Option<&str>) -> Result<Option<Vec<String>>> {
    value
        .map(|s| {
            s.split(',')
                .map(|f| {
                    if FIELDS.contains(&f) {
                        Ok(f.to_owned())
                    } else {
                        Err(Error::Usage(format!("Unknown result field: {f}")))
                    }
                })
                .collect()
        })
        .transpose()
}
/// Project named paths without changing their values.
#[must_use]
pub fn select(value: &Value, fields: Option<&[String]>) -> Value {
    fields.map_or_else(
        || value.clone(),
        |fields| {
            Value::Object(
                fields
                    .iter()
                    .map(|f| {
                        let selected = f
                            .split('.')
                            .try_fold(value, |v, k| v.get(k))
                            .cloned()
                            .unwrap_or(Value::Null);
                        (f.clone(), selected)
                    })
                    .collect(),
            )
        },
    )
}
fn text(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(v) => v.clone(),
        _ => value.to_string(),
    }
}
fn csv_line(values: &[String]) -> Result<String> {
    let mut writer = csv::WriterBuilder::new().from_writer(Vec::new());
    writer
        .write_record(values)
        .map_err(|e| Error::Integrity(e.to_string()))?;
    let bytes = writer
        .into_inner()
        .map_err(|e| Error::Integrity(e.to_string()))?;
    String::from_utf8(bytes).map_err(|e| Error::Integrity(e.to_string()))
}
/// Incremental output with one header and no retained batch rows.
pub struct Renderer {
    format: Format,
    columns: Option<Vec<String>>,
    rows: usize,
    batch: bool,
    layout: Option<crate::table::Layout>,
}
impl Renderer {
    /// Start an output stream in the chosen encoding.
    #[must_use]
    pub const fn new(format: Format, batch: bool) -> Self {
        Self {
            format,
            columns: None,
            rows: 0,
            batch,
            layout: None,
        }
    }
    /// Emit one detached public result or pass-through row.
    pub fn row(&mut self, value: &Value, io: &mut dyn Io) -> Result<()> {
        match self.format {
            Format::Ndjson => io.stdout(&format!("{}\n", serde_json::to_string(value)?))?,
            Format::Json if !self.batch => {
                io.stdout(&format!("{}\n", serde_json::to_string_pretty(value)?))?;
            }
            Format::Json => {
                io.stdout(if self.rows == 0 {
                    "{\n  \"results\": [\n"
                } else {
                    ",\n"
                })?;
                io.stdout(&serde_json::to_string_pretty(value)?)?;
            }
            Format::Csv | Format::Table => self.tabular(value, io)?,
        }
        self.rows += 1;
        Ok(())
    }
    /// Set the tabular order before emitting its first header.
    pub fn columns(&mut self, columns: Vec<String>) {
        if self.columns.is_none() {
            self.columns = Some(columns);
        }
    }
    fn tabular(&mut self, value: &Value, io: &mut dyn Io) -> Result<()> {
        let singleton = Map::from_iter([("value".into(), value.clone())]);
        let object = value.as_object().unwrap_or(&singleton);
        let columns = self.columns.get_or_insert_with(|| {
            if self.format == Format::Table && object.contains_key("status") {
                crate::table::columns(value, self.batch)
            } else {
                ordered(value)
            }
        });
        if self.format == Format::Table
            && columns
                .iter()
                .any(|k| k.strip_prefix("thereabouts_").unwrap_or(k) == "evidence")
        {
            return Err(Error::Usage(
                "Evidence requires --json --evidence, not a table".into(),
            ));
        }
        if self.format == Format::Table && self.layout.is_none() {
            self.layout = Some(crate::table::Layout::new(
                columns,
                value,
                io.terminal_columns(),
            )?);
        }
        if self.rows == 0 {
            io.stdout(&if self.format == Format::Csv {
                csv_line(columns)?
            } else {
                self.layout
                    .as_ref()
                    .ok_or_else(|| Error::Integrity("Missing table layout".into()))?
                    .header(columns)
            })?;
        }
        if self.format == Format::Csv {
            if object.keys().any(|key| !columns.contains(key)) {
                return Err(Error::Usage(
                    "CSV output requires consistent input columns; use NDJSON for varying objects"
                        .into(),
                ));
            }
            io.stdout(&csv_line(
                &columns
                    .iter()
                    .map(|key| text(object.get(key).unwrap_or(&Value::Null)))
                    .collect::<Vec<_>>(),
            )?)?;
        } else {
            let layout = self
                .layout
                .as_ref()
                .ok_or_else(|| Error::Integrity("Missing table layout".into()))?;
            io.stdout(&layout.row(columns, value, false))?;
            if let Some(candidates) = value
                .get("candidates")
                .or_else(|| value.get("thereabouts_candidates"))
                .and_then(Value::as_array)
            {
                for candidate in candidates {
                    let candidate = if object.contains_key("thereabouts_status") {
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
                    io.stdout(&layout.row(columns, &candidate, true))?;
                }
            }
        }
        Ok(())
    }
    /// Close a streamed JSON batch, including an empty one.
    pub fn finish(&self, io: &mut dyn Io) -> Result<()> {
        if self.format == Format::Json && self.batch {
            io.stdout(if self.rows == 0 {
                "{\"results\": []}\n"
            } else {
                "\n  ]\n}\n"
            })?;
        }
        Ok(())
    }
}

/// Public result order, independent of JSON object storage order.
pub(crate) fn ordered(value: &Value) -> Vec<String> {
    let Some(object) = value.as_object() else {
        return vec!["value".into()];
    };
    if object.contains_key("status") {
        FIELDS
            .iter()
            .filter(|f| !f.contains('.') && object.contains_key(**f))
            .map(|f| (*f).into())
            .collect()
    } else {
        object.keys().cloned().collect()
    }
}
