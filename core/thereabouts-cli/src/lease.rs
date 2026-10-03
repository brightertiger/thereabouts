//! `O_EXCL` leases shared with Node; stale takeovers are serialized per incarnation.
use crate::error::{Error, Result};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};
use thereabouts_cli_core::lease::{self, Lease, State};
use thereabouts_core::format::manifest;

static SEQUENCE: AtomicU64 = AtomicU64::new(0);
fn busy() -> Error {
    Error::Usage("Another install is running; retry after it finishes".into())
}
fn milliseconds(time: SystemTime) -> Result<u64> {
    time.duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|v| v.as_millis().try_into().ok())
        .ok_or_else(|| Error::Usage("Cannot read store lock timestamp".into()))
}
fn record() -> Result<String> {
    let now = SystemTime::now();
    let mut token = format!(
        "{:x}",
        Sha256::digest(
            format!(
                "{now:?}:{}:{}",
                std::process::id(),
                SEQUENCE.fetch_add(1, Ordering::Relaxed)
            )
            .as_bytes()
        )
    );
    token.truncate(32);
    Ok(serde_json::to_string(&Lease {
        pid: std::process::id(),
        created_ms: milliseconds(now)?,
        token,
    })?)
}
struct Snapshot {
    contents: String,
    modified_ms: u64,
}
fn snapshot(path: &Path) -> Result<Option<Snapshot>> {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e.into()),
    };
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > lease::MAX_BYTES {
        return Err(Error::Integrity("Invalid store lock file".into()));
    }
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(lease::MAX_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > lease::MAX_BYTES {
        return Err(Error::Integrity("Oversized store lock file".into()));
    }
    let contents = String::from_utf8(bytes)
        .map_err(|_| Error::Integrity("Non-UTF8 store lock file".into()))?;
    Ok(Some(Snapshot {
        contents,
        modified_ms: milliseconds(metadata.modified()?)?,
    }))
}
fn stale(value: &Snapshot) -> Result<bool> {
    Ok(
        match lease::state(
            &value.contents,
            value.modified_ms,
            milliseconds(SystemTime::now())?,
        ) {
            State::Abandoned => true,
            State::Pending => false,
            State::Owner { pid } => {
                if pid == std::process::id() {
                    return Ok(false);
                }
                let pid = sysinfo::Pid::from_u32(pid);
                let mut system = sysinfo::System::new();
                system.refresh_processes_specifics(
                    sysinfo::ProcessesToUpdate::Some(&[pid]),
                    true,
                    sysinfo::ProcessRefreshKind::nothing(),
                );
                system.process(pid).is_none()
            }
        },
    )
}
/// Owned lease removes only its own immutable record; crash recovery uses PID liveness.
pub struct InstallLock {
    path: PathBuf,
    contents: String,
}
impl Drop for InstallLock {
    fn drop(&mut self) {
        if snapshot(&self.path)
            .ok()
            .flatten()
            .is_some_and(|v| v.contents == self.contents)
        {
            let _ = fs::remove_file(&self.path);
        }
    }
}
/// Acquire one shared store lease without any network access.
pub fn lock(root: &Path) -> Result<InstallLock> {
    fs::create_dir_all(root)?;
    acquire(root, ".lock", 0)
}
fn acquire(root: &Path, name: &str, depth: u8) -> Result<InstallLock> {
    if depth > lease::MAX_RECOVERY_DEPTH {
        return Err(busy());
    }
    let path = manifest::artifact_path(root, name)?;
    for _ in 0..4 {
        let contents = record()?;
        match OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut file) => {
                let guard = InstallLock { path, contents };
                file.write_all(guard.contents.as_bytes())?;
                file.sync_all()?;
                return Ok(guard);
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => (),
            Err(e) => return Err(e.into()),
        }
        let Some(previous) = snapshot(&path)? else {
            continue;
        };
        if !stale(&previous)? {
            return Err(busy());
        }
        // A per-record lease prevents concurrent reapers from unlinking a successor.
        // A killed reaper is recovered with the same protocol, at a bounded depth.
        let _reaper = acquire(
            root,
            &lease::recovery_name(name, &previous.contents),
            depth + 1,
        )?;
        if let Some(current) = snapshot(&path)?
            && current.contents == previous.contents
            && stale(&current)?
        {
            fs::remove_file(&path)?;
        }
    }
    Err(busy())
}
