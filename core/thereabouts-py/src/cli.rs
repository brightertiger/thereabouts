//! Python owns only process entry and its optional MCP host.
use pyo3::{exceptions::PyModuleNotFoundError, prelude::*};
use std::{io, path::Path};
use thereabouts_cli::{
    error::{Error, Result},
    io::{Io, SystemIo},
};

struct Host(SystemIo);
impl Io for Host {
    fn read_line(&mut self, line: &mut String) -> io::Result<usize> {
        self.0.read_line(line)
    }
    fn stdout(&mut self, value: &str) -> io::Result<()> {
        self.0.stdout(value)
    }
    fn stderr(&mut self, value: &str) -> io::Result<()> {
        self.0.stderr(value)
    }
    fn env(&self, key: &str) -> Option<String> {
        self.0.env(key)
    }
    fn stdin_tty(&self) -> bool {
        self.0.stdin_tty()
    }
    fn stdout_tty(&self) -> bool {
        self.0.stdout_tty()
    }
    fn mcp(&mut self, root: &Path) -> Result<i32> {
        Python::attach(|py| {
            py.import("thereabouts.mcp_service.server")
                .and_then(|module| module.call_method1("run", (root.to_string_lossy().as_ref(),)))
                .map(|_| 0)
                .map_err(|e| host_error(py, &e))
        })
    }
}
fn host_error(py: Python<'_>, error: &PyErr) -> Error {
    if error.is_instance_of::<PyModuleNotFoundError>(py)
        && error
            .value(py)
            .getattr("name")
            .and_then(|v| v.extract::<String>())
            .is_ok_and(|name| name == "mcp" || name.starts_with("mcp."))
    {
        return Error::Usage("MCP is optional; install thereabouts[mcp] explicitly".into());
    }
    if error
        .value(py)
        .getattr("code")
        .and_then(|v| v.extract::<String>())
        .is_ok_and(|code| code == "data_not_installed")
    {
        let message = error
            .value(py)
            .str()
            .map(|v| v.to_string())
            .unwrap_or_default();
        return Error::Missing(
            message
                .strip_prefix("thereabouts data install ")
                .unwrap_or("core")
                .into(),
        );
    }
    Error::Integrity(error.to_string())
}
#[pyfunction]
#[pyo3(signature=(argv=None))]
fn run_cli(py: Python<'_>, argv: Option<Vec<String>>) -> PyResult<i32> {
    let argv = match argv {
        Some(argv) => argv,
        None => py.import("sys")?.getattr("argv")?.extract()?,
    };
    Ok(py.detach(|| thereabouts_cli::run(&argv, &mut Host(SystemIo))))
}
pub(super) fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(run_cli, module)?)?;
    Ok(())
}
