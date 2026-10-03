//! Platform positioned reads preserve the descriptor identity and never share a seek cursor.
use std::{fs::File, io};
#[cfg(unix)]
pub(super) fn read(file: &File, bytes: &mut [u8], offset: u64) -> io::Result<()> {
    use std::os::unix::fs::FileExt;
    file.read_exact_at(bytes, offset)
}
#[cfg(windows)]
pub(super) fn read(file: &File, mut bytes: &mut [u8], mut offset: u64) -> io::Result<()> {
    use std::os::windows::fs::FileExt;
    while !bytes.is_empty() {
        match file.seek_read(bytes, offset) {
            Ok(0) => return Err(io::ErrorKind::UnexpectedEof.into()),
            Ok(n) => {
                bytes = &mut bytes[n..];
                offset += n as u64;
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
        }
    }
    Ok(())
}
#[cfg(not(any(unix, windows)))]
pub(super) fn read(_file: &File, _bytes: &mut [u8], _offset: u64) -> io::Result<()> {
    // WASM supplies host file access in its binding package, not through std::fs.
    Err(io::ErrorKind::Unsupported.into())
}
