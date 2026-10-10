//! Resumable archive transfer and all-or-nothing dataset activation.
use crate::{
    archive,
    error::{Error, Result},
    index::{Index, ReleasePack},
    store::{self, Active, Pointer},
    transfer::{Locator, Source},
};
use std::{
    collections::BTreeMap,
    fs::{self, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
};
use thereabouts_cli_core::archive::Summary;
use thereabouts_core::format::{
    manifest::{self, Manifest},
    verify,
};

/// Allow for filesystem bookkeeping beyond the download and expanded archive.
pub const DISK_MARGIN_BYTES: u64 = 64 * 1024 * 1024;

/// Reject an install before downloading when its conservative peak does not fit:
/// every compressed download plus its expanded tar stream, which bounds the files.
pub fn precheck(root: &Path, bytes: u64) -> Result<()> {
    admit(fs2::available_space(root)?, bytes)
}
fn admit(available: u64, bytes: u64) -> Result<()> {
    let needed = bytes
        .checked_add(DISK_MARGIN_BYTES)
        .ok_or_else(|| Error::Usage("Install size overflow".into()))?;
    if available < needed {
        return Err(Error::Usage(format!(
            "Not enough disk space: need {needed} bytes, available {available} bytes"
        )));
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
    let mut pin = selection(root, version, requested, source)?;
    let bytes = requested.iter().try_fold(0u64, |sum, name| {
        let pack = dataset
            .packs
            .get(name)
            .ok_or_else(|| Error::Integrity("Missing release family".into()))?;
        sum.checked_add(pack.size)
            .and_then(|sum| sum.checked_add(pack.unpacked_size))
            .ok_or_else(|| Error::Integrity("Install size overflow".into()))
    })?;
    precheck(root, bytes)?;
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
fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\"'\"'"))
}
fn selection(
    root: &Path,
    version: &str,
    requested: &[String],
    source: &dyn Source,
) -> Result<Active> {
    if let Some(pin) = store::active(root)? {
        if pin.data_version == version {
            return Ok(pin);
        }
        if pin.packs.keys().any(|name| !requested.contains(name)) {
            let all = store::FAMILIES
                .iter()
                .filter(|name| {
                    pin.packs.contains_key(**name) || requested.iter().any(|v| v == **name)
                })
                .copied()
                .collect::<Vec<_>>()
                .join(" ");
            let origin = source
                .origin()
                .map_or_else(String::new, |s| format!(" --from {}", quote(&s)));
            let directory = quote(&root.to_string_lossy());
            let current = &pin.data_version;
            let requested = requested.join(" ");
            return Err(Error::Usage(format!(
                "Changing dataset version requires every active family. Run:\nthereabouts data install {all} --version {version}{origin} --data-dir {directory}\nTo keep the active version:\nthereabouts data install {requested} --version {current}{origin} --data-dir {directory}"
            )));
        }
        return Ok(Active {
            data_version: version.into(),
            packs: BTreeMap::new(),
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
fn identity(path: &Path, version: &str, name: &str, pack: &ReleasePack) -> Result<Manifest> {
    let info = verify::verify(path)?;
    if info.data_version != version || info.family != name || info.format_minor != pack.format_minor
    {
        return Err(Error::Integrity(
            "Downloaded pack differs from release index identity".into(),
        ));
    }
    Ok(info)
}
/// The archive holds exactly the verified inventory: no stray file is installed.
fn inventory(summary: &Summary, info: &Manifest) -> Result<()> {
    let mut expected = info
        .files
        .iter()
        .map(|f| f.path.as_str())
        .chain(std::iter::once("manifest.json"))
        .collect::<Vec<_>>();
    expected.sort_unstable();
    let mut found = summary
        .entries
        .iter()
        .map(|e| e.path.as_str())
        .collect::<Vec<_>>();
    found.sort_unstable();
    if found != expected {
        return Err(Error::Integrity(
            "Archive files differ from the pack manifest".into(),
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
        if receipt.sha256 != pack.sha256 || receipt.size != pack.size {
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
        let summary = archive::extract(&archive, &staging, pack.unpacked_size)?;
        inventory(&summary, &identity(&staging, version, name, pack)?)?;
        let receipt = manifest::artifact_path(&staging, ".archive.json")?;
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
    if offset > pack.size {
        drop(file);
        fs::remove_file(&path)?;
        return Err(Error::Integrity(
            "Partial download exceeds advertised size".into(),
        ));
    }
    if offset < pack.size {
        let remote = Locator {
            url: &pack.url,
            api_url: pack.api_url.as_deref(),
        };
        let mut input = source.open_file(remote, offset, pack.size)?;
        let mut remaining = pack.size - offset;
        let mut buffer = vec![0; 65536];
        loop {
            let count = input
                .read(&mut buffer)
                .map_err(Error::download_interrupted)?;
            if count == 0 {
                break;
            }
            let count64 = u64::try_from(count)
                .map_err(|_| Error::Integrity("Transfer count overflow".into()))?;
            if count64 > remaining {
                return Err(Error::Integrity("Download exceeds advertised size".into()));
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
            return Err(Error::download_interrupted("incomplete response"));
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

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn admission_needs_archive_expansion_and_small_margin_only() {
        assert!(admit(128 * 1024 * 1024, 2048).is_ok());
        let needed = DISK_MARGIN_BYTES + 2048;
        assert!(admit(needed, 2048).is_ok());
        let error = admit(needed - 1, 2048).unwrap_err();
        assert_eq!(error.exit_code(), 2);
        assert!(error.to_string().contains("Not enough disk"));
    }
}
