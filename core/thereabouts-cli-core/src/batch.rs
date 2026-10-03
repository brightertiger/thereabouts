//! Reverse batches consume one row at a time and preserve named input columns.
use crate::{
    Format,
    error::{Error, Result},
    io::Io,
    render::{self, Renderer},
};
use serde_json::{Map, Value};
use std::{
    cell::RefCell,
    io::{self, BufRead, BufReader, Cursor, Read},
};
use thereabouts_core::{
    format::Pack,
    result::{LookupResult, Status},
};

/// Input and output policy; paths are labels only and never opened here.
#[derive(Clone, Debug, serde::Serialize, serde::Deserialize)]
pub struct Options {
    /// Filename used for explicit NDJSON extension detection; "-" denotes stdin.
    pub filename: String,
    /// Explicit latitude header; automatic names are otherwise exact.
    pub lat_col: Option<String>,
    /// Explicit longitude header.
    pub lon_col: Option<String>,
    /// Include source details in structured output.
    pub evidence: bool,
    /// Exit one on any miss when no row failed.
    pub strict: bool,
    /// Comma-separated ordered public field paths.
    pub fields: Option<String>,
    /// Explicit output format after host TTY selection.
    pub format: Format,
}

struct Input<'a, 'host> {
    host: &'a RefCell<&'host mut dyn Io>,
    file: Option<Box<dyn BufRead>>,
    pending: Cursor<Vec<u8>>,
}
impl Input<'_, '_> {
    fn line(&mut self, line: &mut String) -> io::Result<usize> {
        if let Some(file) = &mut self.file {
            file.read_line(line)
        } else {
            self.host.borrow_mut().read_line(line)
        }
    }
}
impl Read for Input<'_, '_> {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        if buffer.is_empty() {
            return Ok(0);
        }
        if self.pending.position() == self.pending.get_ref().len() as u64 {
            let mut line = String::new();
            self.line(&mut line)?;
            self.pending = Cursor::new(line.into_bytes());
        }
        self.pending.read(buffer)
    }
}
struct Output<'a> {
    pack: &'a Pack,
    options: &'a Options,
    fields: Option<Vec<String>>,
    renderer: Renderer,
    format: Format,
    failed: bool,
    missed: bool,
    input_fields: Vec<String>,
}
impl Output<'_> {
    fn row(
        &mut self,
        mut input: Map<String, Value>,
        coords: Option<(f64, f64)>,
        why: Option<String>,
        io: &mut dyn Io,
    ) -> Result<()> {
        if input.keys().any(|k| k.starts_with("thereabouts_")) {
            return Err(Error::Usage(
                "Input columns beginning thereabouts_ are reserved for results".into(),
            ));
        }
        for name in &self.input_fields {
            input.entry(name.clone()).or_insert(Value::Null);
        }
        let answer = if let Some((lat, lon)) = coords {
            self.pack.reverse(lat, lon, self.options.evidence)?
        } else {
            let mut invalid = LookupResult::empty(Status::InvalidInput);
            invalid.hint =
                Some(why.unwrap_or_else(|| "Each row requires numeric lat and lon".into()));
            invalid
        };
        self.failed |= crate::exit(answer.status, false) == 2;
        self.missed |= answer.status == Status::NotFound;
        let mut result = serde_json::to_value(answer)?;
        if let Some(object) = result.as_object_mut() {
            object.entry("hint").or_insert(Value::Null);
            if self.options.evidence {
                object.entry("evidence").or_insert(Value::Null);
            }
        }
        let mut columns = if self.input_fields.is_empty() {
            input.keys().cloned().collect()
        } else {
            self.input_fields.clone()
        };
        let selected = self.fields.clone().unwrap_or_else(|| {
            if self.format == Format::Table {
                crate::table::columns(&result, true)
            } else {
                render::ordered(&result)
            }
        });
        columns.extend(selected.into_iter().map(|k| format!("thereabouts_{k}")));
        self.renderer.columns(columns);
        if let Value::Object(fields) = render::select(&result, self.fields.as_deref()) {
            input.extend(
                fields
                    .into_iter()
                    .map(|(k, v)| (format!("thereabouts_{k}"), v)),
            );
        }
        self.renderer.row(&Value::Object(input), io)
    }
}
fn numeric(value: Option<&Value>) -> Option<f64> {
    value.and_then(Value::as_f64)
}
fn column(headers: &csv::StringRecord, explicit: Option<&str>, accepted: &[&str]) -> Result<usize> {
    let matches: Vec<_> = headers
        .iter()
        .enumerate()
        .filter(|(_, v)| explicit.map_or_else(|| accepted.contains(v), |wanted| *v == wanted))
        .collect();
    if matches.len() != 1 {
        return Err(Error::Usage(
            "CSV coordinate headers are absent or ambiguous; specify --lat-col and --lon-col"
                .into(),
        ));
    }
    matches
        .first()
        .map(|(i, _)| *i)
        .ok_or_else(|| Error::Usage("Missing coordinate column".into()))
}
/// Consume a batch without owning the host's filesystem or process streams.
pub fn run(
    pack: &Pack,
    options: &Options,
    input: Option<Box<dyn BufRead>>,
    io: &mut dyn Io,
) -> Result<i32> {
    let file = &options.filename;
    let format = options.format;
    let lat_col = options.lat_col.as_deref();
    let lon_col = options.lon_col.as_deref();
    let host = RefCell::new(io);
    let mut source = Input {
        host: &host,
        file: input,
        pending: Cursor::new(Vec::new()),
    };
    let mut first = String::new();
    while source.line(&mut first)? > 0 && first.trim().is_empty() {
        first.clear();
    }
    if first.is_empty() {
        Renderer::new(format, true).finish(*host.borrow_mut())?;
        return Ok(0);
    }
    let mut output = Output {
        pack,
        options,
        fields: render::fields(options.fields.as_deref())?,
        renderer: Renderer::new(format, true),
        format,
        failed: false,
        missed: false,
        input_fields: Vec::new(),
    };
    if std::path::Path::new(file)
        .extension()
        .is_some_and(|e| e.eq_ignore_ascii_case("ndjson") || e.eq_ignore_ascii_case("jsonl"))
        || first.trim_start().starts_with(['{', '['])
    {
        if lat_col.is_some() || lon_col.is_some() {
            return Err(Error::Usage("Column flags apply only to CSV input".into()));
        }
        if matches!(format, Format::Csv | Format::Table) {
            let temporary = host.borrow_mut().temporary()?;
            let (file, fields) =
                crate::batch_spool::collect(&first, temporary, |line| source.line(line))?;
            output.input_fields = fields;
            source.file = Some(Box::new(BufReader::new(file)));
            first.clear();
            source.line(&mut first)?;
        }
        ndjson(&mut source, first, &mut output, &host)?;
    } else if !first.is_empty() {
        source.pending = Cursor::new(first.into_bytes());
        csv(source, &mut output, lat_col, lon_col, &host)?;
    }
    output.renderer.finish(*host.borrow_mut())?;
    Ok(if output.failed {
        5
    } else {
        i32::from(options.strict && output.missed)
    })
}

fn ndjson(
    source: &mut Input<'_, '_>,
    mut first: String,
    output: &mut Output<'_>,
    host: &RefCell<&mut dyn Io>,
) -> Result<()> {
    loop {
        match serde_json::from_str::<Map<String, Value>>(&first) {
            Ok(input) => {
                let coords = numeric(input.get("lat")).zip(numeric(input.get("lon")));
                output.row(input, coords, None, *host.borrow_mut())?;
            }
            Err(error) => {
                let input =
                    Map::from_iter([("input".into(), Value::String(first.trim_end().into()))]);
                output.row(
                    input,
                    None,
                    Some(format!("Invalid NDJSON object: {error}")),
                    *host.borrow_mut(),
                )?;
            }
        }
        first.clear();
        if source.line(&mut first)? == 0 {
            break;
        }
    }
    Ok(())
}

fn csv(
    source: Input<'_, '_>,
    output: &mut Output<'_>,
    lat_col: Option<&str>,
    lon_col: Option<&str>,
    host: &RefCell<&mut dyn Io>,
) -> Result<()> {
    let mut csv = csv::ReaderBuilder::new().flexible(true).from_reader(source);
    let headers = csv
        .headers()
        .map_err(|e| Error::Usage(e.to_string()))?
        .clone();
    let unique: std::collections::BTreeSet<_> = headers.iter().collect();
    if headers.len() < 2 {
        return Err(Error::Usage("Expected comma-separated CSV with lat/lon columns, or NDJSON objects with lat/lon keys".into()));
    }
    if unique.len() != headers.len()
        || headers
            .iter()
            .any(|v| v.is_empty() || v.starts_with("thereabouts_"))
    {
        return Err(Error::Usage(
            "CSV headers must be unique, nonempty and outside thereabouts_".into(),
        ));
    }
    output.input_fields = headers.iter().map(str::to_owned).collect();
    let lat = column(&headers, lat_col, &["lat", "latitude"])?;
    let lon = column(&headers, lon_col, &["lon", "longitude", "lng"])?;
    for record in csv.records() {
        match record {
            Ok(record) => {
                let input = headers
                    .iter()
                    .enumerate()
                    .map(|(i, h)| (h.into(), Value::String(record.get(i).unwrap_or("").into())))
                    .collect();
                let coords = (record.len() == headers.len())
                    .then(|| {
                        record
                            .get(lat)?
                            .parse::<f64>()
                            .ok()
                            .zip(record.get(lon)?.parse::<f64>().ok())
                    })
                    .flatten();
                output.row(input, coords, None, *host.borrow_mut())?;
            }
            Err(error) => {
                let input = headers.iter().map(|h| (h.into(), Value::Null)).collect();
                output.row(input, None, Some(error.to_string()), *host.borrow_mut())?;
            }
        }
    }
    Ok(())
}
