//! Injectable process IO; no global stream or environment access in command policy.
use std::io::{self, BufRead, IsTerminal, Write};

pub use thereabouts_cli_core::io::{Io, Temporary};

/// Native stdio adapter, also used by the Python console entry.
pub struct SystemIo;
impl Io for SystemIo {
    fn temporary(&mut self) -> io::Result<Box<dyn Temporary>> {
        Ok(Box::new(tempfile::tempfile()?))
    }
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
    fn terminal_columns(&self) -> usize {
        self.env("COLUMNS")
            .and_then(|v| v.parse().ok())
            .filter(|n| (1..=10_000).contains(n))
            .or_else(|| {
                terminal_size::terminal_size_of(io::stdout()).map(|(width, _)| usize::from(width.0))
            })
            .filter(|n| *n > 0)
            .unwrap_or(80)
    }
    fn stdout_tty(&self) -> bool {
        io::stdout().is_terminal()
    }
}
