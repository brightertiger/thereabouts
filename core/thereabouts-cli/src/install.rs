//! Resumable archive transfer and all-or-nothing dataset activation.
use crate::{
    archive,
    error::{Error, Result},
    index::{Index, ReleasePack},
    store::{self, Active, Pointer},
    transfer::Source,
};
use std::{
    collections::BTreeMap,
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};
use thereabouts_core::format::{manifest, verify};

/// Reserve five GiB beyond the peak download plus expanded archive size.
pub const FREE_SPACE_FLOOR: u64 = 5 * 1024 * 1024 * 1024;

/// Reject an install before any downloads when its conservative peak does not fit.
pub fn precheck(root: &Path, bytes: u64) -> Result<()> {
    let needed = bytes
        .checked_mul(2)
        .and_then(|v| v.checked_add(FREE_SPACE_FLOOR))
        .ok_or_else(|| Error::Integrity("Install size overflow".into()))?;
    if fs2::available_space(root)? < needed {
        return Err(Error::Integrity(
            "Install would leave less than 5 GiB free".into(),
        ));
    }
    Ok(())
}
/// Load the explicit source index, bounded by the source implementation.
pub fn index(source: &dyn Source) -> Result<Index> {
    let bytes = source.index()?;
    if bytes.len() > 16 * 1024 * 1024 {
        return Err(Error::Integrity("Oversized release index".into()));
    }
    let index: Index = serde_json::from_slice(&bytes)?;
    index.validate()?;
    Ok(index)
}
/// Install selected family archives and atomically activate their shared dataset.
pub fn install(
    root: &Path,
    source: &dyn Source,
    requested: &[String],
    version: Option<&str>,
) -> Result<Active> {
    if requested.is_empty() {
        return Err(Error::Usage("Name at least one pack to install".into()));
    }
    let index = index(source)?;
    let (version, dataset) = index.select(requested, version)?;
    let _lock = store::lock(root)?;
    let bytes = requested.iter().try_fold(0u64, |sum, name| {
        sum.checked_add(
            dataset
                .packs
                .get(name)
                .ok_or_else(|| Error::Integrity("Missing release family".into()))?
                .bytes,
        )
        .ok_or_else(|| Error::Integrity("Install size overflow".into()))
    })?;
    precheck(root, bytes)?;
    let mut pin = selection(root, version, requested)?;
    for name in requested {
        let pack = dataset
            .packs
            .get(name)
            .ok_or_else(|| Error::Integrity("Missing release family".into()))?;
        let pointer = install_one(root, source, version, name, pack)?;
        pin.packs.insert(name.clone(), pointer);
    }
    store::activate(root, &pin)?;
    Ok(pin)
}
fn selection(root: &Path, version: &str, requested: &[String]) -> Result<Active> {
    if let Some(pin) = store::active(root)? {
        return Ok(if pin.data_version == version {
            pin
        } else {
            Active {
                data_version: version.into(),
                packs: BTreeMap::new(),
            }
        });
    }
    let mut pin = Active {
        data_version: version.into(),
        packs: BTreeMap::new(),
    };
    for name in store::FAMILIES {
        let current = manifest::artifact_path(root, &format!("packs/{name}/current.json"))?;
        if current.exists() && !requested.iter().any(|v| v == name) {
            let path = store::installed(root, name)?;
            if manifest::read(&path)?.data_version == version {
                pin.packs.insert(name.into(), pointer(root, &path)?);
            }
        }
    }
    Ok(pin)
}
fn pointer(root: &Path, path: &Path) -> Result<Pointer> {
    Ok(Pointer {
        path: path
            .strip_prefix(root)
            .map_err(|_| Error::Integrity("Install escaped store".into()))?
            .to_string_lossy()
            .replace('\\', "/"),
        manifest_sha256: manifest::digest(&manifest::artifact_path(path, "manifest.json")?)?,
    })
}
fn identity(path: &Path, version: &str, name: &str, pack: &ReleasePack) -> Result<()> {
    let info = verify::verify(path)?;
    if info.data_version != version || info.family != name || info.format_minor != pack.format_minor
    {
        return Err(Error::Integrity(
            "Downloaded pack differs from release index identity".into(),
        ));
    }
    Ok(())
}
fn install_one(
    root: &Path,
    source: &dyn Source,
    version: &str,
    name: &str,
    pack: &ReleasePack,
) -> Result<Pointer> {
    let destination = manifest::artifact_path(root, &format!("packs/{name}/{version}"))?;
    if destination.exists() {
        identity(&destination, version, name, pack)?;
        let receipt: ReleasePack =
            store::read_json(&manifest::artifact_path(&destination, ".archive.json")?)?;
        if receipt.sha256 != pack.sha256 || receipt.bytes != pack.bytes {
            return Err(Error::Integrity(
                "Installed release archive identity changed".into(),
            ));
        }
        return pointer(root, &destination);
    }
    let archive = download(root, source, pack)?;
    let staging = manifest::artifact_path(root, &format!(".staging/{}", pack.sha256))?;
    // The lock protects this exact staging path; failed extraction is disposable.
    if staging.exists() {
        fs::remove_dir_all(&staging)?;
    }
    fs::create_dir_all(&staging)?;
    let result = (|| {
        archive::extract(&mut File::open(&archive)?, &staging, pack.bytes)?;
        identity(&staging, version, name, pack)?;
        let receipt = manifest::artifact_path(&staging, ".archive.json")?;
        if receipt.exists() {
            return Err(Error::Integrity(
                "Archive contains reserved installer receipt".into(),
            ));
        }
        fs::write(receipt, serde_json::to_vec(pack)?)?;
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::rename(&staging, &destination)?;
        pointer(root, &destination)
    })();
    if staging.exists() {
        fs::remove_dir_all(&staging)?;
    }
    if result.is_ok() {
        fs::remove_file(archive)?;
    }
    result
}
fn download(root: &Path, source: &dyn Source, pack: &ReleasePack) -> Result<PathBuf> {
    let path = manifest::artifact_path(root, &format!(".downloads/{}.part", pack.sha256))?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .append(true)
        .open(&path)?;
    let offset = file.metadata()?.len();
    if offset > pack.bytes {
        drop(file);
        fs::remove_file(&path)?;
        return Err(Error::Integrity(
            "Partial download exceeds advertised size".into(),
        ));
    }
    if offset < pack.bytes {
        let mut input = source.open(&pack.url, offset, pack.bytes)?;
        let mut remaining = pack.bytes - offset;
        let mut buffer = vec![0; 65536];
        loop {
            let count = input.read(&mut buffer)?;
            if count == 0 {
                break;
            }
            let count64 = u64::try_from(count)
                .map_err(|_| Error::Integrity("Transfer count overflow".into()))?;
            if count64 > remaining {
                return Err(Error::Integrity("Download exceeds advertised size".into()));
            }
            if fs2::available_space(root)? < FREE_SPACE_FLOOR + count64 {
                return Err(Error::Integrity(
                    "Download reached the 5 GiB free-space floor".into(),
                ));
            }
            file.write_all(
                buffer
                    .get(..count)
                    .ok_or_else(|| Error::Integrity("Invalid transfer count".into()))?,
            )?;
            remaining -= count64;
        }
        file.sync_all()?;
        if remaining != 0 {
            return Err(Error::Integrity(
                "Interrupted download; run install again to resume".into(),
            ));
        }
    }
    drop(file);
    if manifest::digest(&path)? != pack.sha256 {
        fs::remove_file(&path)?;
        return Err(Error::Integrity(
            "Downloaded archive checksum mismatch".into(),
        ));
    }
    Ok(path)
}
