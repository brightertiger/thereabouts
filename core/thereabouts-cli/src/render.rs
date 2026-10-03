//! Output never changes result semantics, and batch rendering retains one row.
use crate::{
    args::Format,
    error::{Error, Result},
    io::Io,
};
use serde_json::{Map, Value};

pub(crate) const FIELDS: &[&str] = &[
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
pub(crate) fn fields(value: Option<&str>) -> Result<Option<Vec<String>>> {
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
pub(crate) fn select(value: &Value, fields: Option<&[String]>) -> Value {
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
pub(crate) struct Renderer {
    format: Format,
    columns: Option<Vec<String>>,
    rows: usize,
    batch: bool,
}
impl Renderer {
    pub const fn new(format: Format, batch: bool) -> Self {
        Self {
            format,
            columns: None,
            rows: 0,
            batch,
        }
    }
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
    fn tabular(&mut self, value: &Value, io: &mut dyn Io) -> Result<()> {
        let singleton = Map::from_iter([("value".into(), value.clone())]);
        let object = value.as_object().unwrap_or(&singleton);
        if self.columns.is_none() {
            let columns: Vec<_> = object.keys().cloned().collect();
            self.line(&columns, io)?;
            self.columns = Some(columns);
        }
        let columns = self.columns.as_deref().unwrap_or_default();
        if object.keys().any(|key| !columns.contains(key)) {
            return Err(Error::Usage("CSV/table output requires consistent input columns; use NDJSON for varying objects".into()));
        }
        self.line(
            &columns
                .iter()
                .map(|key| text(object.get(key).unwrap_or(&Value::Null)))
                .collect::<Vec<_>>(),
            io,
        )
    }
    fn line(&self, values: &[String], io: &mut dyn Io) -> Result<()> {
        if self.format == Format::Csv {
            io.stdout(&csv_line(values)?)?;
        } else {
            let clean: Vec<String> = values
                .iter()
                .map(|v| {
                    v.chars()
                        .map(|c| if c.is_control() { ' ' } else { c })
                        .collect()
                })
                .collect();
            io.stdout(&format!("{}\n", clean.join(" | ")))?;
        }
        Ok(())
    }
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
