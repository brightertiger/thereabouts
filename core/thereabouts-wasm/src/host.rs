//! The embedding host owns file handles, streams, and temporary storage.
use js_sys::Uint8Array;
use std::{io, path::Path, sync::Arc};
use thereabouts_core::format::reader::{ReadAt, Source};
use wasm_bindgen::prelude::*;

#[wasm_bindgen(raw_module = "../runtime/host.js")]
extern "C" {
    #[wasm_bindgen(catch, js_name = canonicalRoot)]
    fn canonical_root(path: &str) -> Result<String, JsValue>;
    #[wasm_bindgen(catch, js_name = openHandle)]
    fn open_handle(path: &str) -> Result<u32, JsValue>;
    #[wasm_bindgen(catch, js_name = fileSize)]
    fn file_size(id: u32) -> Result<f64, JsValue>;
    #[wasm_bindgen(catch, js_name = readAt)]
    fn read_at(id: u32, offset: f64, length: u32) -> Result<Uint8Array, JsValue>;
    #[wasm_bindgen(js_name = closeHandle)]
    fn close_handle(id: u32);
    #[wasm_bindgen(catch, js_name = temporary)]
    fn temporary() -> Result<u32, JsValue>;
    #[wasm_bindgen(catch, js_name = writeAt)]
    fn write_at(id: u32, offset: f64, bytes: &[u8]) -> Result<(), JsValue>;
    #[wasm_bindgen(catch, js_name = readLine)]
    fn read_line() -> Result<String, JsValue>;
    #[wasm_bindgen(js_name = terminalColumns)]
    fn terminal_columns() -> u32;
    #[wasm_bindgen(catch, js_name = stdout)]
    fn stdout(value: &str) -> Result<(), JsValue>;
    #[wasm_bindgen(catch, js_name = stderr)]
    fn stderr(value: &str) -> Result<(), JsValue>;
}
#[allow(clippy::needless_pass_by_value)] // map_err owns the JS exception.
fn failure(value: JsValue) -> io::Error {
    let code = js_sys::Reflect::get(&value, &"code".into())
        .ok()
        .and_then(|v| v.as_string());
    let kind = match code.as_deref() {
        Some("ENOSPC") => io::ErrorKind::StorageFull,
        Some("EPIPE") => io::ErrorKind::BrokenPipe,
        _ => io::ErrorKind::Other,
    };
    let text = js_sys::Reflect::get(&value, &"message".into())
        .ok()
        .and_then(|v| v.as_string())
        .unwrap_or_else(|| format!("{value:?}"));
    io::Error::new(kind, text)
}
#[derive(Debug)]
pub(crate) struct File {
    id: u32,
    size: u64,
    offset: u64,
}
impl File {
    pub(crate) fn open(path: &Path) -> io::Result<Self> {
        let id = open_handle(
            path.to_str()
                .ok_or_else(|| io::Error::other("Non-UTF8 path"))?,
        )
        .map_err(failure)?;
        Self::from_id(id)
    }
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    fn from_id(id: u32) -> io::Result<Self> {
        let size = match file_size(id) {
            Ok(size)
                if size.is_finite()
                    && (0.0..=9_007_199_254_740_991.0).contains(&size)
                    && size.fract() == 0.0 =>
            {
                size as u64
            }
            _ => {
                close_handle(id);
                return Err(io::Error::other("Invalid host file size"));
            }
        };
        Ok(Self {
            id,
            size,
            offset: 0,
        })
    }
}
impl Drop for File {
    fn drop(&mut self) {
        close_handle(self.id);
    }
}
impl ReadAt for File {
    fn size(&self) -> u64 {
        self.size
    }
    #[allow(clippy::cast_precision_loss)]
    fn read_at(&self, offset: u64, bytes: &mut [u8]) -> thereabouts_core::Result<()> {
        let length = u32::try_from(bytes.len()).map_err(|_| io::Error::other("Read too large"))?;
        let end = offset
            .checked_add(u64::from(length))
            .ok_or_else(|| io::Error::other("Read overflow"))?;
        if end > self.size {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "Read exceeds file").into());
        }
        let output = read_at(self.id, offset as f64, length).map_err(failure)?;
        if output.length() != length {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "Short host read").into());
        }
        output.copy_to(bytes);
        Ok(())
    }
}
impl io::Read for File {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        let length = usize::try_from(self.size.saturating_sub(self.offset))
            .unwrap_or(usize::MAX)
            .min(bytes.len());
        let target = bytes
            .get_mut(..length)
            .ok_or_else(|| io::Error::other("Read range"))?;
        ReadAt::read_at(self, self.offset, target).map_err(|e| io::Error::other(e.to_string()))?;
        self.offset += length as u64;
        Ok(length)
    }
}
impl io::Write for File {
    #[allow(clippy::cast_precision_loss)]
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        write_at(self.id, self.offset as f64, bytes).map_err(failure)?;
        self.offset += bytes.len() as u64;
        self.size = self.size.max(self.offset);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}
impl io::Seek for File {
    fn seek(&mut self, position: io::SeekFrom) -> io::Result<u64> {
        self.offset = match position {
            io::SeekFrom::Start(n) => Some(n),
            io::SeekFrom::Current(n) => self.offset.checked_add_signed(n),
            io::SeekFrom::End(n) => self.size.checked_add_signed(n),
        }
        .filter(|n| *n <= 9_007_199_254_740_991)
        .ok_or_else(|| io::Error::other("Invalid seek"))?;
        Ok(self.offset)
    }
}
pub(crate) struct Host;
impl Source for Host {
    fn open(&self, path: &Path) -> thereabouts_core::Result<Arc<dyn ReadAt>> {
        Ok(Arc::new(File::open(path)?))
    }
}
impl thereabouts_cli_core::io::Io for Host {
    fn read_line(&mut self, line: &mut String) -> io::Result<usize> {
        let value = read_line().map_err(failure)?;
        let size = value.len();
        line.push_str(&value);
        Ok(size)
    }
    fn stdout(&mut self, value: &str) -> io::Result<()> {
        stdout(value).map_err(failure)
    }
    fn stderr(&mut self, value: &str) -> io::Result<()> {
        stderr(value).map_err(failure)
    }
    fn env(&self, _: &str) -> Option<String> {
        None
    }
    fn stdin_tty(&self) -> bool {
        false
    }
    fn terminal_columns(&self) -> usize {
        terminal_columns() as usize
    }
    fn stdout_tty(&self) -> bool {
        false
    }
    fn temporary(&mut self) -> io::Result<Box<dyn thereabouts_cli_core::io::Temporary>> {
        Ok(Box::new(File::from_id(temporary().map_err(failure)?)?))
    }
}

pub(crate) fn root(path: &str) -> thereabouts_core::Result<std::path::PathBuf> {
    Ok(std::path::PathBuf::from(
        canonical_root(path).map_err(failure)?,
    ))
}
