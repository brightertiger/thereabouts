//! Thin `CPython` boundary. Dataset policy and lookup semantics live in the core.
mod cli;
mod columns;
mod result;
mod store;
use pyo3::{
    exceptions::PyValueError,
    prelude::*,
    types::{PyDict, PyList},
};
use serde_json::Value;
use std::{
    path::Path,
    sync::{Arc, Mutex},
};
use thereabouts_core::{Error, format::Pack};
#[cfg(feature = "writer")]
use thereabouts_writer as writer;

fn error(py: Python<'_>, error: &Error) -> PyErr {
    coded_error(py, error.code(), &error.to_string())
}
fn coded_error(py: Python<'_>, code: &str, message: &str) -> PyErr {
    let name = match code {
        "data_not_installed" => "DataNotInstalledError",
        "pack_not_found" => "PackNotFoundError",
        "writer_input_error" => "WriterInputError",
        "writer_error" => "WriterError",
        "incompatible_data" => "IncompatibleDataError",
        "closed_geocoder" => "ClosedGeocoderError",
        "resource_limit" => "ResourceLimitError",
        _ => "CorruptPackError",
    };
    match py
        .import("thereabouts.errors")
        .and_then(|m| m.getattr(name))
        .and_then(|c| c.call1((message,)))
    {
        Ok(exception) => PyErr::from_value(exception),
        Err(e) => e,
    }
}
fn value_to_python(py: Python<'_>, value: &Value) -> PyResult<Py<PyAny>> {
    Ok(match value {
        Value::Null => py.None(),
        Value::Bool(v) => v.into_pyobject(py)?.to_owned().into_any().unbind(),
        Value::String(v) => v.into_pyobject(py)?.into_any().unbind(),
        Value::Number(v) => {
            if let Some(n) = v.as_i64() {
                n.into_pyobject(py)?.into_any().unbind()
            } else if let Some(n) = v.as_u64() {
                n.into_pyobject(py)?.into_any().unbind()
            } else {
                v.as_f64().into_pyobject(py)?.into_any().unbind()
            }
        }
        Value::Array(values) => {
            let list = PyList::empty(py);
            for v in values {
                list.append(value_to_python(py, v)?)?;
            }
            list.into_any().unbind()
        }
        Value::Object(values) => {
            let dict = PyDict::new(py);
            for (k, v) in values {
                dict.set_item(k, value_to_python(py, v)?)?;
            }
            dict.into_any().unbind()
        }
    })
}
/// Native handle; closing drops this owner's reference while active batches finish.
#[pyclass(module = "thereabouts._core")]
struct Geocoder {
    pack: Mutex<Option<Arc<Pack>>>,
}
impl Geocoder {
    fn pack(&self, py: Python<'_>) -> PyResult<Arc<Pack>> {
        self.pack
            .lock()
            .map_err(|_| error(py, &Error::Closed))?
            .clone()
            .ok_or_else(|| error(py, &Error::Closed))
    }
}
#[pymethods]
impl Geocoder {
    #[pyo3(signature=(lat,lon,*,evidence=false))]
    fn reverse(&self, py: Python<'_>, lat: f64, lon: f64, evidence: bool) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .reverse(lat, lon, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    #[pyo3(signature=(cell,*,evidence=false))]
    #[allow(clippy::wrong_self_convention)] // Public API verb, not a constructor.
    fn from_h3(&self, py: Python<'_>, cell: &str, evidence: bool) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .from_h3(cell, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    #[pyo3(signature=(code, *, country=None, evidence=false))]
    fn postal(
        &self,
        py: Python<'_>,
        code: &str,
        country: Option<&str>,
        evidence: bool,
    ) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .postal(code, country, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    #[pyo3(signature=(codes, *, country=None))]
    fn postal_columns<'py>(
        &self,
        py: Python<'py>,
        codes: Vec<String>,
        country: Option<&str>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let pack = self.pack(py)?;
        columns::forward(py, codes, |code| pack.postal(code, country, false))
    }
    #[pyo3(signature=(code, *, scheme=None, country=None, evidence=false))]
    fn airport(
        &self,
        py: Python<'_>,
        code: &str,
        scheme: Option<&str>,
        country: Option<&str>,
        evidence: bool,
    ) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .airport(code, scheme, country, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    #[pyo3(signature=(codes, *, scheme=None, country=None))]
    fn airport_columns<'py>(
        &self,
        py: Python<'py>,
        codes: Vec<String>,
        scheme: Option<&str>,
        country: Option<&str>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let pack = self.pack(py)?;
        columns::forward(py, codes, |code| pack.airport(code, scheme, country, false))
    }
    #[pyo3(signature=(code, *, country=None, evidence=false))]
    fn locode(
        &self,
        py: Python<'_>,
        code: &str,
        country: Option<&str>,
        evidence: bool,
    ) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .locode(code, country, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    #[pyo3(signature=(codes, *, country=None))]
    fn locode_columns<'py>(
        &self,
        py: Python<'py>,
        codes: Vec<String>,
        country: Option<&str>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let pack = self.pack(py)?;
        columns::forward(py, codes, |code| pack.locode(code, country, false))
    }
    #[pyo3(signature=(number, *, country=None, evidence=false))]
    fn phone(
        &self,
        py: Python<'_>,
        number: &str,
        country: Option<&str>,
        evidence: bool,
    ) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .phone_in_country(number, country, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    fn phone_columns<'py>(
        &self,
        py: Python<'py>,
        numbers: Vec<String>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let pack = self.pack(py)?;
        columns::forward(py, numbers, |number| pack.phone(number, false))
    }
    #[pyo3(signature=(address, *, evidence=false))]
    fn ip(&self, py: Python<'_>, address: &str, evidence: bool) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .ip(address, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    fn ip_columns<'py>(
        &self,
        py: Python<'py>,
        addresses: Vec<String>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let pack = self.pack(py)?;
        columns::forward(py, addresses, |address| pack.ip(address, false))
    }
    #[pyo3(signature=(value, *, country=None, series=None, evidence=false))]
    fn plate(
        &self,
        py: Python<'_>,
        value: &str,
        country: Option<&str>,
        series: Option<&str>,
        evidence: bool,
    ) -> PyResult<Py<PyAny>> {
        result::encode(
            py,
            &self
                .pack(py)?
                .plate(value, country, series, evidence)
                .map_err(|e| error(py, &e))?,
        )
    }
    #[pyo3(signature=(values, *, country=None, series=None))]
    fn plate_columns<'py>(
        &self,
        py: Python<'py>,
        values: Vec<String>,
        country: Option<&str>,
        series: Option<&str>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let pack = self.pack(py)?;
        columns::forward(py, values, |value| {
            pack.plate(value, country, series, false)
        })
    }
    #[pyo3(signature=(name, *, country=None, subdivision=None, limit=5, prefer=None, scope="cities", evidence=false))]
    #[allow(clippy::too_many_arguments)] // Mirrors the public keyword-only Python API.
    fn geocode(
        &self,
        py: Python<'_>,
        name: &str,
        country: Option<&str>,
        subdivision: Option<&str>,
        limit: usize,
        prefer: Option<&str>,
        scope: &str,
        evidence: bool,
    ) -> PyResult<Py<PyAny>> {
        let options = thereabouts_core::geocode::Options {
            country,
            subdivision,
            limit,
            prefer,
            scope,
            evidence,
        };
        result::encode(
            py,
            &self
                .pack(py)?
                .geocode(name, options)
                .map_err(|e| error(py, &e))?,
        )
    }
    #[pyo3(signature=(names, *, country=None, subdivision=None, limit=5, prefer=None, scope="cities"))]
    #[allow(clippy::too_many_arguments)] // Same options as scalar geocoding; GIL released in the batch loop.
    fn geocode_columns<'py>(
        &self,
        py: Python<'py>,
        names: Vec<String>,
        country: Option<&str>,
        subdivision: Option<&str>,
        limit: usize,
        prefer: Option<&str>,
        scope: &str,
    ) -> PyResult<Bound<'py, PyDict>> {
        let pack = self.pack(py)?;
        let options = thereabouts_core::geocode::Options {
            country,
            subdivision,
            limit,
            prefer,
            scope,
            evidence: false,
        };
        columns::forward(py, names, |name| pack.geocode(name, options))
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        *self.pack.lock().map_err(|_| error(py, &Error::Closed))? = None;
        Ok(())
    }
    #[allow(clippy::needless_pass_by_value)] // PyO3 owns each extracted borrow guard.
    fn reverse_columns<'py>(
        &self,
        py: Python<'py>,
        lat: numpy::PyReadonlyArray1<'py, f64>,
        lon: numpy::PyReadonlyArray1<'py, f64>,
    ) -> PyResult<Bound<'py, PyDict>> {
        columns::reverse(py, &self.pack(py)?, &lat, &lon)
    }
}
#[pyfunction]
#[pyo3(signature=(path, *, verify=false, core=None))]
fn open(py: Python<'_>, path: &str, verify: bool, core: Option<&Geocoder>) -> PyResult<Geocoder> {
    let shared = core.map(|c| c.pack(py)).transpose()?;
    let pack = py
        .detach(|| {
            let pack = Pack::open(Path::new(path), verify)?;
            if let Some(core) = shared {
                pack.with_core(core)
            } else {
                Ok(pack)
            }
        })
        .map_err(|e| error(py, &e))?;
    Ok(Geocoder {
        pack: Mutex::new(Some(Arc::new(pack))),
    })
}
#[cfg(feature = "writer")]
#[pyfunction]
fn write_pack(
    py: Python<'_>,
    dataset_dir: &str,
    family: &str,
    output_dir: &str,
    options: &Bound<'_, PyDict>,
) -> PyResult<Py<PyAny>> {
    let json: String = py
        .import("json")?
        .call_method1("dumps", (options,))?
        .extract()?;
    let options: writer::Options = serde_json::from_str(&json)
        .map_err(|e| coded_error(py, "writer_input_error", &e.to_string()))?;
    let manifest = py
        .detach(|| {
            writer::write_pack(
                Path::new(dataset_dir),
                family,
                Path::new(output_dir),
                &options,
            )
        })
        .map_err(|e| coded_error(py, e.code(), &e.to_string()))?;
    value_to_python(
        py,
        &serde_json::to_value(manifest).map_err(|e| PyValueError::new_err(e.to_string()))?,
    )
}
#[pyfunction]
fn verify_pack(py: Python<'_>, path: &str) -> PyResult<Py<PyAny>> {
    let manifest = py
        .detach(|| thereabouts_core::format::verify::verify(Path::new(path)))
        .map_err(|e| coded_error(py, e.code(), &e.to_string()))?;
    value_to_python(
        py,
        &serde_json::to_value(manifest).map_err(|e| PyValueError::new_err(e.to_string()))?,
    )
}
#[pyfunction]
fn pack_info(py: Python<'_>, path: &str) -> PyResult<Py<PyAny>> {
    let manifest = thereabouts_core::format::manifest::read(Path::new(path))
        .map_err(|e| coded_error(py, e.code(), &e.to_string()))?;
    value_to_python(
        py,
        &serde_json::to_value(manifest).map_err(|e| PyValueError::new_err(e.to_string()))?,
    )
}
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    store::register(m)?;
    cli::register(m)?;
    m.add_class::<Geocoder>()?;
    m.add_function(wrap_pyfunction!(open, m)?)?;
    #[cfg(feature = "writer")]
    m.add_function(wrap_pyfunction!(write_pack, m)?)?;
    m.add_function(wrap_pyfunction!(verify_pack, m)?)?;
    m.add_function(wrap_pyfunction!(pack_info, m)?)?;
    {
        use thereabouts_cli_core::transport;
        m.add("MAX_ARCHIVE_BYTES", transport::MAX_ARCHIVE_BYTES)?;
        m.add("MAX_UNPACKED_BYTES", transport::MAX_UNPACKED_BYTES)?;
        m.add("DEFAULT_RELEASE_URL", transport::DEFAULT_RELEASE_URL)?;
        m.add("INDEX_FORMAT", transport::INDEX_FORMAT)?;
        m.add("ARCHIVE_SUFFIX", transport::ARCHIVE_SUFFIX)?;
    }
    Ok(())
}
