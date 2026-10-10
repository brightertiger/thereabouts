//! `data install dataset`: restore the Parquet dataset from a release's table zips.
//!
//! The release index names the dataset install manifest by size and digest. The
//! manifest lists every table zip with its members and every loose document. Each file
//! downloads with resume into `.downloads/`, zips expand through the shared reader into
//! staging (the pack path rules apply), every file is checked against its listed size
//! and SHA-256, and the tree becomes `dataset/<version>/` only when it is complete.
use crate::{
    archive,
    error::{Error, Result},
    install::{self, Remote},
    store,
    transfer::Source,
};
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
};
use thereabouts_cli_core::{
    transport::MAX_UNPACKED_BYTES,
    zip::{MANIFEST_FORMAT, MAX_ENTRIES},
};
use thereabouts_core::format::manifest;

/// One file the manifest promises, by its dataset-relative path.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
struct Member {
    path: String,
    size: u64,
    sha256: String,
}
#[derive(Debug, Deserialize)]
struct Archive {
    name: String,
    url: String,
    #[serde(default)]
    api_url: Option<String>,
    size: u64,
    sha256: String,
    unpacked_size: u64,
    files: Vec<Member>,
}
#[derive(Debug, Deserialize)]
struct Document {
    path: String,
    url: String,
    #[serde(default)]
    api_url: Option<String>,
    size: u64,
    sha256: String,
}
#[derive(Debug, Deserialize)]
struct Manifest {
    format: u32,
    version: String,
    archives: Vec<Archive>,
    files: Vec<Document>,
}
impl Archive {
    fn remote(&self) -> Remote<'_> {
        Remote {
            url: &self.url,
            api_url: self.api_url.as_deref(),
            size: self.size,
            sha256: &self.sha256,
        }
    }
}
impl Document {
    fn remote(&self) -> Remote<'_> {
        Remote {
            url: &self.url,
            api_url: self.api_url.as_deref(),
            size: self.size,
            sha256: &self.sha256,
        }
    }
}
fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
impl Manifest {
    /// Every promised file, refusing unsafe paths, duplicates and impossible sizes.
    fn expected(&self, version: &str) -> Result<BTreeMap<String, Member>> {
        if self.format != MANIFEST_FORMAT || self.version != version {
            return Err(Error::Integrity(
                "Dataset manifest differs from the release index".into(),
            ));
        }
        let mut expected = BTreeMap::new();
        let mut names = BTreeSet::new();
        let mut add = |member: Member| -> Result<()> {
            manifest::artifact_path(Path::new(""), &member.path)?;
            if !digest(&member.sha256) || expected.insert(member.path.clone(), member).is_some() {
                return Err(Error::Integrity("Invalid dataset manifest entry".into()));
            }
            Ok(())
        };
        for archive in &self.archives {
            let total = archive
                .files
                .iter()
                .map(|f| f.size)
                .try_fold(0u64, u64::checked_add);
            if !names.insert(archive.name.as_str())
                || archive.files.is_empty()
                || archive.files.len() > MAX_ENTRIES
                || total != Some(archive.unpacked_size)
                || archive.unpacked_size > MAX_UNPACKED_BYTES
                || !digest(&archive.sha256)
            {
                return Err(Error::Integrity("Invalid dataset archive identity".into()));
            }
            for member in &archive.files {
                if !member.path.contains('/') {
                    return Err(Error::Integrity("Dataset archives hold table files".into()));
                }
                add(member.clone())?;
            }
        }
        for document in &self.files {
            if document.path.contains('/') {
                return Err(Error::Integrity(
                    "Dataset documents are top-level files".into(),
                ));
            }
            add(Member {
                path: document.path.clone(),
                size: document.size,
                sha256: document.sha256.clone(),
            })?;
        }
        Ok(expected)
    }
}
/// Every regular file below `root`, as `/`-separated relative paths.
fn listing(root: &Path) -> Result<BTreeMap<String, PathBuf>> {
    let mut found = BTreeMap::new();
    let mut pending = vec![root.to_owned()];
    while let Some(directory) = pending.pop() {
        for item in fs::read_dir(&directory)? {
            let item = item?;
            let kind = item.file_type()?;
            if kind.is_dir() {
                pending.push(item.path());
            } else if kind.is_file() {
                let relative = item
                    .path()
                    .strip_prefix(root)
                    .map_err(|_| Error::Integrity("Dataset file escaped its root".into()))?
                    .to_string_lossy()
                    .replace('\\', "/");
                found.insert(relative, item.path());
            } else {
                return Err(Error::Integrity(
                    "Dataset holds a link or special file".into(),
                ));
            }
        }
    }
    Ok(found)
}
/// The tree holds exactly the promised files with their sizes and digests.
fn verify(root: &Path, expected: &BTreeMap<String, Member>) -> Result<()> {
    let found = listing(root)?;
    if found.keys().ne(expected.keys()) {
        return Err(Error::Integrity(
            "Dataset files differ from the dataset manifest".into(),
        ));
    }
    for (path, file) in &found {
        let member = expected
            .get(path)
            .ok_or_else(|| Error::Integrity("Unexpected dataset file".into()))?;
        if file.metadata()?.len() != member.size || manifest::digest(file)? != member.sha256 {
            return Err(Error::Integrity(format!(
                "Dataset file differs from the dataset manifest: {path}"
            )));
        }
    }
    Ok(())
}
/// Install the newest (or requested) release's dataset under `dataset/<version>/`.
pub(crate) fn install(root: &Path, source: &dyn Source, version: Option<&str>) -> Result<Value> {
    let index = install::index(source)?;
    let (version, file) = index.select_dataset(version)?;
    store::component(version)?;
    let _lock = store::lock(root)?;
    let described = install::download(
        root,
        source,
        &Remote {
            url: &file.url,
            api_url: file.api_url.as_deref(),
            size: file.size,
            sha256: &file.sha256,
        },
    )?;
    let listed: Manifest = serde_json::from_slice(&fs::read(&described)?)?;
    let expected = listed.expected(version)?;
    let destination = manifest::artifact_path(root, &format!("dataset/{version}"))?;
    let bytes = expected.values().map(|m| m.size).sum::<u64>();
    let summary = |installed: bool| {
        json!({"dataset":{"version":version,"path":destination,"files":expected.len(),
            "bytes":bytes,"installed":installed}})
    };
    if destination.exists() {
        verify(&destination, &expected)?;
        fs::remove_file(&described)?;
        return Ok(summary(false));
    }
    let downloads = listed
        .archives
        .iter()
        .map(|a| a.size.checked_add(a.unpacked_size))
        .chain(listed.files.iter().map(|d| Some(d.size)))
        .try_fold(0u64, |sum, size| {
            size.and_then(|size| sum.checked_add(size))
        })
        .ok_or_else(|| Error::Integrity("Install size overflow".into()))?;
    install::precheck(root, downloads)?;
    let staging = manifest::artifact_path(root, &format!(".staging/dataset-{version}"))?;
    if staging.exists() {
        fs::remove_dir_all(&staging)?;
    }
    fs::create_dir_all(&staging)?;
    let mut fetched = vec![described];
    let result = restore(root, source, &listed, &staging, &mut fetched).and_then(|()| {
        verify(&staging, &expected)?;
        if let Some(parent) = destination.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::rename(&staging, &destination)?;
        Ok(())
    });
    if staging.exists() {
        fs::remove_dir_all(&staging)?;
    }
    result?;
    for path in fetched {
        if path.exists() {
            fs::remove_file(path)?;
        }
    }
    Ok(summary(true))
}
/// Download and expand every archive and document into `staging`, each checked.
fn restore(
    root: &Path,
    source: &dyn Source,
    listed: &Manifest,
    staging: &Path,
    fetched: &mut Vec<PathBuf>,
) -> Result<()> {
    for item in &listed.archives {
        let path = install::download(root, source, &item.remote())?;
        fetched.push(path.clone());
        let summary = archive::extract_zip(&path, staging, item.unpacked_size)?;
        let mut found: Vec<_> = summary
            .entries
            .into_iter()
            .map(|e| Member {
                path: e.path,
                size: e.size,
                sha256: e.sha256,
            })
            .collect();
        let mut promised = item.files.clone();
        found.sort_by(|a, b| a.path.cmp(&b.path));
        promised.sort_by(|a, b| a.path.cmp(&b.path));
        if found != promised {
            return Err(Error::Integrity(format!(
                "Dataset archive differs from the dataset manifest: {}",
                item.name
            )));
        }
    }
    for document in &listed.files {
        let path = install::download(root, source, &document.remote())?;
        fetched.push(path.clone());
        let target = manifest::artifact_path(staging, &document.path)?;
        if target.exists() {
            return Err(Error::Integrity("Duplicate dataset file".into()));
        }
        fs::copy(&path, &target)?;
    }
    Ok(())
}
