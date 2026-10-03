//! Injectable process IO; no global stream or environment access in command policy.
use std::io::{self, BufRead, IsTerminal, Write};

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
    /// Optional host-owned MCP server; the native library has no Python SDK dependency.
    fn mcp(&mut self, _root: &std::path::Path) -> crate::error::Result<i32> {
        Err(crate::error::Error::Usage(
            "MCP requires the Python host with thereabouts[mcp] installed".into(),
        ))
    }
}

/// Native stdio adapter, also used by the Python console entry.
pub struct SystemIo;
impl Io for SystemIo {
    fn read_line(&mut self, line: &mut String) -> io::Result<usize> {
        io::stdin().lock().read_line(line)
    }
    fn stdout(&mut self, value: &str) -> io::Result<()> {
        let mut output = io::stdout().lock();
        output.write_all(value.as_bytes())?;
        output.flush()
    }
    fn stderr(&mut self, value: &str) -> io::Result<()> {
        let mut output = io::stderr().lock();
        output.write_all(value.as_bytes())?;
        output.flush()
    }
    fn env(&self, key: &str) -> Option<String> {
        std::env::var(key).ok()
    }
    fn stdin_tty(&self) -> bool {
        io::stdin().is_terminal()
    }
    fn stdout_tty(&self) -> bool {
        io::stdout().is_terminal()
    }
}
