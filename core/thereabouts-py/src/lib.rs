//! Thin `CPython` boundary. Dataset policy and lookup semantics live in the core.
mod columns;
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
fn result_value(
    py: Python<'_>,
    result: &thereabouts_core::result::LookupResult,
) -> PyResult<Py<PyAny>> {
    value_to_python(
        py,
        &serde_json::to_value(result).map_err(|e| PyValueError::new_err(e.to_string()))?,
    )
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
        result_value(
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
        result_value(
            py,
            &self
                .pack(py)?
                .from_h3(cell, evidence)
                .map_err(|e| error(py, &e))?,
        )
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
#[pyo3(signature=(path, *, verify=false))]
fn open(py: Python<'_>, path: &str, verify: bool) -> PyResult<Geocoder> {
    let pack = py
        .detach(|| Pack::open(Path::new(path), verify))
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
    m.add_class::<Geocoder>()?;
    m.add_function(wrap_pyfunction!(open, m)?)?;
    #[cfg(feature = "writer")]
    m.add_function(wrap_pyfunction!(write_pack, m)?)?;
    m.add_function(wrap_pyfunction!(verify_pack, m)?)?;
    m.add_function(wrap_pyfunction!(pack_info, m)?)?;
    Ok(())
}
