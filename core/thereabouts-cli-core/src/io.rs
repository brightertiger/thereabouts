//! Host-owned streams and temporary storage; policy performs no system calls.
use std::io;
/// Temporary backing storage for tabular NDJSON, released on drop.
pub trait Temporary: io::Read + io::Write + io::Seek {}
impl<T: io::Read + io::Write + io::Seek> Temporary for T {}
/// Host interface used by both the native process and embedded CLI tests.
pub trait Io {
    /// Consume one input line; zero means EOF.
    fn read_line(&mut self, line: &mut String) -> io::Result<usize>;
    /// Write result bytes.
    fn stdout(&mut self, value: &str) -> io::Result<()>;
    /// Write diagnostics or confirmation prompts.
    fn stderr(&mut self, value: &str) -> io::Result<()>;
    /// Read one host environment variable.
    fn env(&self, key: &str) -> Option<String>;
    /// Whether standard input supports an interactive confirmation.
    fn stdin_tty(&self) -> bool;
    /// Whether default output should be a human table.
    fn stdout_tty(&self) -> bool;
    /// Create seekable temporary storage; the host removes it when dropped.
    fn temporary(&mut self) -> io::Result<Box<dyn Temporary>>;
    /// Optional host-owned MCP server; the native library has no Python SDK dependency.
    fn mcp(&mut self, _root: &std::path::Path) -> crate::error::Result<i32> {
        Err(crate::error::Error::Usage(
            "MCP requires the Python host with thereabouts[mcp] installed".into(),
        ))
    }
}
