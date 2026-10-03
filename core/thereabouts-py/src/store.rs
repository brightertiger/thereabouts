//! Shared native discovery for Python and command-line callers.
use pyo3::prelude::*;
use std::path::Path;
use thereabouts_cli::{error::Error, io::SystemIo, store};

fn error(py: Python<'_>, error: &Error) -> PyErr {
    let code = match error {
        Error::Missing(_) => "data_not_installed",
        Error::Pack(error) => error.code(),
        _ => "corrupt_pack",
    };
    super::coded_error(py, code, &error.to_string())
}
#[pyfunction]
#[pyo3(signature=(explicit=None))]
fn data_directory(explicit: Option<&str>) -> PyResult<String> {
    store::directory(explicit.map(Path::new), &SystemIo)
        .map(|p| p.to_string_lossy().into_owned())
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
}
#[pyfunction]
fn installed_pack(py: Python<'_>, root: &str, family: &str) -> PyResult<String> {
    store::installed(Path::new(root), family)
        .map(|p| p.to_string_lossy().into_owned())
        .map_err(|e| error(py, &e))
}
pub(super) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(data_directory, m)?)?;
    m.add_function(wrap_pyfunction!(installed_pack, m)?)?;
    Ok(())
}
