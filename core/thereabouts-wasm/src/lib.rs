//! Node supplies positioned IO; WASM owns pack admission, lookups and CLI policy.
mod host;
mod query;
use std::sync::Arc;
use thereabouts_core::{
    Error,
    format::{Pack, manifest, reader::Reader},
};
use wasm_bindgen::prelude::*;

fn error(code: &str, message: &str, exit: i32) -> JsValue {
    let value = js_sys::Error::new(message);
    let _ = js_sys::Reflect::set(&value, &"code".into(), &code.into());
    let _ = js_sys::Reflect::set(&value, &"exitCode".into(), &exit.into());
    value.into()
}
#[allow(clippy::needless_pass_by_value)] // map_err consumes the core failure.
fn core_error(e: Error) -> JsValue {
    error(
        e.code(),
        &e.to_string(),
        if matches!(e, Error::Input(_)) { 2 } else { 4 },
    )
}
#[allow(clippy::needless_pass_by_value)] // map_err consumes the CLI failure.
fn cli_error(e: thereabouts_cli_core::error::Error) -> JsValue {
    if matches!(&e, thereabouts_cli_core::error::Error::Io(io) if io.kind() == std::io::ErrorKind::BrokenPipe)
    {
        return error("EPIPE", &e.to_string(), 0);
    }
    error("cli_error", &e.to_string(), e.exit_code())
}
fn json<T: serde::Serialize>(value: &T) -> Result<String, JsValue> {
    serde_json::to_string(value).map_err(|e| core_error(e.into()))
}
/// An explicitly closed handle releases shards and their host file descriptors.
#[wasm_bindgen]
pub struct Geocoder {
    pack: Option<Arc<Pack>>,
}
impl Geocoder {
    fn get(&self) -> Result<&Arc<Pack>, JsValue> {
        self.pack.as_ref().ok_or_else(|| core_error(Error::Closed))
    }
}
#[wasm_bindgen]
impl Geocoder {
    /// Open one family without loading payloads or implicitly fetching data.
    #[wasm_bindgen(js_name = open)]
    pub fn open(path: &str, verify: bool) -> Result<Self, JsValue> {
        let root = host::root(path).map_err(core_error)?;
        let pack = Pack::open_with(&Reader::new(&root, &host::Host), verify).map_err(core_error)?;
        Ok(Self {
            pack: Some(Arc::new(pack)),
        })
    }
    /// Check the installed core namespace before enriching a forward pack.
    #[wasm_bindgen(js_name = openWithCore)]
    pub fn open_with_core(path: &str, verify: bool, core: &Self) -> Result<Self, JsValue> {
        let root = host::root(path).map_err(core_error)?;
        let pack = Pack::open_with(&Reader::new(&root, &host::Host), verify)
            .and_then(|p| p.with_core(Arc::clone(core.get().map_err(|_| Error::Closed)?)))
            .map_err(core_error)?;
        Ok(Self {
            pack: Some(Arc::new(pack)),
        })
    }
    /// Close is idempotent; future calls fail with `closed_geocoder`.
    pub fn close(&mut self) {
        self.pack = None;
    }
    /// Numeric coordinates retain IEEE invalid values for the core's validation.
    pub fn reverse(&self, lat: f64, lon: f64, evidence: bool) -> Result<String, JsValue> {
        json(
            &self
                .get()?
                .reverse(lat, lon, evidence)
                .map_err(core_error)?,
        )
    }
    /// Typed dispatch of one explicit forward verb or H3 cell.
    pub fn query(&self, request: &str) -> Result<String, JsValue> {
        let query: query::Query =
            serde_json::from_str(request).map_err(|e| core_error(e.into()))?;
        json(&query.run(self.get()?).map_err(core_error)?)
    }
    /// Stream CSV or NDJSON through the portable parser and renderer.
    pub fn batch(&self, options: &str, path: Option<String>) -> Result<i32, JsValue> {
        let options = serde_json::from_str(options).map_err(|e| cli_error(e.into()))?;
        let input: Option<Box<dyn std::io::BufRead>> = path
            .map(|p| {
                host::File::open(&host::root(&p).map_err(|e| std::io::Error::other(e.to_string()))?)
                    .map(|f| Box::new(std::io::BufReader::new(f)) as Box<dyn std::io::BufRead>)
            })
            .transpose()
            .map_err(|e| cli_error(e.into()))?;
        thereabouts_cli_core::batch::run(self.get()?, &options, input, &mut host::Host)
            .map_err(cli_error)
    }
}
/// Shared field registry; Node does not carry a second list.
#[wasm_bindgen(js_name = fields)]
#[must_use]
pub fn fields() -> String {
    thereabouts_cli_core::render::FIELDS.join("\n")
}
/// Portable scalar result rendering and exit status.
#[wasm_bindgen(js_name = render)]
#[allow(clippy::needless_pass_by_value)] // wasm-bindgen accepts owned optional strings.
pub fn render(
    value: &str,
    format: &str,
    fields: Option<String>,
    strict: bool,
) -> Result<i32, JsValue> {
    let value: serde_json::Value = serde_json::from_str(value).map_err(|e| cli_error(e.into()))?;
    let format = format.parse().map_err(cli_error)?;
    let selected = thereabouts_cli_core::render::fields(fields.as_deref()).map_err(cli_error)?;
    let mut renderer = thereabouts_cli_core::render::Renderer::new(format, false);
    if let Some(columns) = &selected {
        renderer.columns(columns.clone());
    }
    renderer
        .row(
            &thereabouts_cli_core::render::select(&value, selected.as_deref()),
            &mut host::Host,
        )
        .map_err(cli_error)?;
    renderer.finish(&mut host::Host).map_err(cli_error)?;
    let status = value
        .get("status")
        .cloned()
        .map(serde_json::from_value)
        .transpose()
        .map_err(|e| cli_error(e.into()))?;
    Ok(status.map_or(0, |s| thereabouts_cli_core::exit(s, strict)))
}
/// Read and validate manifest and sizes, optionally all artifact hashes/structures.
#[wasm_bindgen(js_name = packInfo)]
pub fn pack_info(path: &str, full: bool) -> Result<String, JsValue> {
    let root = host::root(path).map_err(core_error)?;
    let reader = Reader::new(&root, &host::Host);
    let info = if full {
        thereabouts_core::format::verify::verify_with(&reader)
    } else {
        manifest::read_with(&reader)
    };
    json(&info.map_err(core_error)?)
}

/// Render management records with one shared header; rows carry no lookup status.
#[wasm_bindgen(js_name = renderRows)]
pub fn render_rows(rows: &str, format: &str) -> Result<(), JsValue> {
    let rows: Vec<serde_json::Value> =
        serde_json::from_str(rows).map_err(|e| cli_error(e.into()))?;
    let mut renderer =
        thereabouts_cli_core::render::Renderer::new(format.parse().map_err(cli_error)?, false);
    for row in rows {
        renderer.row(&row, &mut host::Host).map_err(cli_error)?;
    }
    renderer.finish(&mut host::Host).map_err(cli_error)
}

/// Share the native transaction address policy without a platform addon.
#[wasm_bindgen(js_name = lockPort)]
#[must_use]
pub fn lock_port(canonical_root: &str) -> u16 {
    thereabouts_cli_core::lock_port(canonical_root)
}
