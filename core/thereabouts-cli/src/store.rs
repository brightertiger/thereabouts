//! A single atomic pointer pins all active families to one dataset release.
use crate::{
    error::{Error, Result},
    io::Io,
};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};
use thereabouts_core::format::manifest::{self, Manifest};

/// Families accepted by install and discovery; names remain in the core pack.
pub const FAMILIES: [&str; 7] = [
    "core", "postal", "airports", "locode", "phone", "ip", "plates",
];

/// Immutable identity of a selected pack.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Pointer {
    /// Store-relative directory.
    pub path: String,
    /// SHA-256 of manifest.json, independent of downloaded archive identity.
    pub manifest_sha256: String,
}
/// One transaction selects a dataset version and its available families.
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Active {
    /// Dataset identity shared by all entries.
    pub data_version: String,
    /// Only these families are visible when this pointer exists.
    pub packs: BTreeMap<String, Pointer>,
}

/// Validate a portable, single directory component.
pub fn component(value: &str) -> Result<()> {
    let stem = value
        .split('.')
        .next()
        .unwrap_or_default()
        .to_ascii_uppercase();
    let reserved = ["CON", "PRN", "AUX", "NUL"].contains(&stem.as_str())
        || (stem.starts_with("COM") || stem.starts_with("LPT"))
            && stem.len() == 4
            && stem
                .as_bytes()
                .last()
                .is_some_and(|b| (b'1'..=b'9').contains(b));
    if value.is_empty()
        || value.len() > 128
        || value.starts_with('.')
        || value.ends_with('.')
        || reserved
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._-".contains(&b))
    {
        return Err(Error::Integrity(
            "Invalid release directory component".into(),
        ));
    }
    Ok(())
}
/// Reject unknown families before constructing any filesystem path.
pub fn family(value: &str) -> Result<()> {
    if FAMILIES.contains(&value) {
        Ok(())
    } else {
        Err(Error::Usage(format!("Unknown pack family: {value}")))
    }
}
/// Resolve explicit, environment, then platform user-data paths.
pub fn directory(explicit: Option<&Path>, io: &dyn Io) -> Result<PathBuf> {
    if let Some(path) = explicit {
        return expand(path, io);
    }
    if let Some(value) = io.env("THEREABOUTS_DATA").filter(|v| !v.is_empty()) {
        return expand(Path::new(&value), io);
    }
    platform_directory(std::env::consts::OS, io)
}
/// Platform policy is injectable for cross-platform parity tests.
pub fn platform_directory(platform: &str, io: &dyn Io) -> Result<PathBuf> {
    let home = || {
        io.env("HOME")
            .map(PathBuf::from)
            .ok_or_else(|| Error::Usage("Set THEREABOUTS_DATA or HOME".into()))
    };
    match platform {
        "macos" => Ok(home()?.join("Library/Application Support/Thereabouts")),
        "windows" => io
            .env("LOCALAPPDATA")
            .map(|v| PathBuf::from(v).join("Thereabouts"))
            .ok_or_else(|| Error::Usage("Set THEREABOUTS_DATA or LOCALAPPDATA".into())),
        _ => Ok(io
            .env("XDG_DATA_HOME")
            .filter(|v| !v.is_empty())
            .map_or_else(
                || home().map(|p| p.join(".local/share")),
                |v| Ok(PathBuf::from(v)),
            )?
            .join("thereabouts")),
    }
}
fn expand(path: &Path, io: &dyn Io) -> Result<PathBuf> {
    if let Ok(tail) = path.strip_prefix("~") {
        let home = io
            .env("HOME")
            .or_else(|| io.env("USERPROFILE"))
            .ok_or_else(|| Error::Usage("Cannot expand home directory".into()))?;
        return Ok(PathBuf::from(home).join(tail));
    }
    Ok(path.to_owned())
}
/// Read bounded JSON metadata; reject symlinked store paths.
pub fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> Result<T> {
    let meta = fs::symlink_metadata(path)?;
    if !meta.is_file() || meta.len() > 16 * 1024 * 1024 {
        return Err(Error::Integrity("Invalid store metadata file".into()));
    }
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}
/// Load the atomic dataset pin, if present.
pub fn active(root: &Path) -> Result<Option<Active>> {
    let path = manifest::artifact_path(root, "active.json")?;
    if !path.exists() {
        return Ok(None);
    }
    let pin: Active = read_json(&path)?;
    component(&pin.data_version)?;
    for name in pin.packs.keys() {
        family(name)?;
    }
    Ok(Some(pin))
}
fn resolve(root: &Path, name: &str, pointer: &Pointer, version: Option<&str>) -> Result<PathBuf> {
    resolve_inner(root, name, pointer, version)
        .map_err(|e| e.at_pack(&root.join(&pointer.path), name))
}
fn resolve_inner(
    root: &Path,
    name: &str,
    pointer: &Pointer,
    version: Option<&str>,
) -> Result<PathBuf> {
    let path = manifest::artifact_path(root, &pointer.path)?;
    if manifest::digest(&manifest::artifact_path(&path, "manifest.json")?)?
        != pointer.manifest_sha256
    {
        return Err(Error::Integrity("Active manifest digest mismatch".into()));
    }
    let info = manifest::read(&path)?;
    if info.family != name || version.is_some_and(|v| v != info.data_version) {
        return Err(Error::Integrity("Active pack identity mismatch".into()));
    }
    let ordinary = format!("packs/{name}/{}", info.data_version);
    let escaped: String = info
        .data_version
        .bytes()
        .map(|b| {
            if b.is_ascii_alphanumeric() || b"_.-~".contains(&b) {
                char::from(b).to_string()
            } else {
                format!("%{b:02X}")
            }
        })
        .collect();
    let legacy = format!("packs/{name}/v-{escaped}/{}", pointer.manifest_sha256);
    if pointer.path != ordinary && pointer.path != legacy {
        return Err(Error::Integrity(
            "Active path differs from immutable pack identity".into(),
        ));
    }
    Ok(path)
}
/// Discover a family without network access; old current.json remains readable.
pub fn installed(root: &Path, name: &str) -> Result<PathBuf> {
    family(name)?;
    if let Some(pin) = active(root)? {
        let pointer = pin
            .packs
            .get(name)
            .ok_or_else(|| Error::Missing(name.into()))?;
        return resolve(root, name, pointer, Some(&pin.data_version));
    }
    let path = manifest::artifact_path(root, &format!("packs/{name}/current.json"))?;
    if path.exists() {
        return resolve(root, name, &read_json(&path)?, None);
    }
    if name == "core" && manifest::artifact_path(root, "packs/reverse/current.json")?.exists() {
        return Err(thereabouts_core::Error::Incompatible(
            "Legacy reverse data requires a format-2 core pack".into(),
        )
        .into());
    }
    Err(Error::Missing(name.into()))
}
/// All selected compatible manifests, in family order.
pub fn inventory(root: &Path) -> Result<Vec<(PathBuf, Manifest)>> {
    let mut result = Vec::new();
    for name in FAMILIES {
        match installed(root, name) {
            Ok(path) => {
                let info = manifest::read(&path)?;
                result.push((path, info));
            }
            Err(Error::Missing(_)) => (),
            Err(error) => return Err(error),
        }
    }
    Ok(result)
}
/// Both guards are owned for the whole transaction and released by the OS on exit.
pub struct InstallLock {
    _file: File,
    _coordination: std::net::TcpListener,
}
/// Serialize native and JS hosts without a Node native addon or stale leases.
pub fn lock(root: &Path) -> Result<InstallLock> {
    fs::create_dir_all(root)?;
    let path = manifest::artifact_path(root, ".install.lock")?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)?;
    file.try_lock()
        .map_err(|_| Error::Integrity("Another data operation holds the install lock".into()))?;
    let canonical = fs::canonicalize(root)?;
    let canonical = canonical
        .to_str()
        .ok_or_else(|| Error::Usage("Store path must be UTF-8".into()))?;
    let port = thereabouts_cli_core::lock_port(canonical);
    let coordination = std::net::TcpListener::bind((std::net::Ipv4Addr::LOCALHOST, port))
        .map_err(|_| Error::Integrity(format!(
            "Install lock coordination port 127.0.0.1:{port} is busy; another data operation or local process holds it"
        )))?;
    Ok(InstallLock {
        _file: file,
        _coordination: coordination,
    })
}
/// Replace the pin only after every requested installation has verified.
pub fn activate(root: &Path, pin: &Active) -> Result<()> {
    component(&pin.data_version)?;
    for (name, pointer) in &pin.packs {
        resolve(root, name, pointer, Some(&pin.data_version))?;
    }
    validate_core_pins(root, pin)?;
    let path = manifest::artifact_path(root, "active.json")?;
    let temporary = manifest::artifact_path(root, ".active.json.tmp")?;
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(&temporary)?;
    file.write_all(&serde_json::to_vec_pretty(pin)?)?;
    file.sync_all()?;
    fs::rename(temporary, path)?;
    Ok(())
}
/// Remove one family's installations under the store lock.
pub fn remove(root: &Path, name: &str) -> Result<()> {
    family(name)?;
    let _lock = lock(root)?;
    if let Some(mut pin) = active(root)? {
        pin.packs.remove(name);
        activate(root, &pin)?;
    }
    let path = manifest::artifact_path(root, &format!("packs/{name}"))?;
    if path.exists() {
        fs::remove_dir_all(path)?;
    }
    Ok(())
}

fn validate_core_pins(root: &Path, pin: &Active) -> Result<()> {
    use std::sync::Arc;
    use thereabouts_core::format::Pack;
    let Some(pointer) = pin.packs.get("core") else {
        return Ok(());
    };
    let core = Arc::new(Pack::open(
        &resolve(root, "core", pointer, Some(&pin.data_version))?,
        false,
    )?);
    for (family, pointer) in &pin.packs {
        if family != "core" {
            Pack::open(
                &resolve(root, family, pointer, Some(&pin.data_version))?,
                false,
            )?
            .with_core(Arc::clone(&core))?;
        }
    }
    Ok(())
}
