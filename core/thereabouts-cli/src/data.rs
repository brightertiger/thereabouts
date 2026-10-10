//! Explicit data commands are the only path from CLI policy to transfer sources.
use crate::{
    args::Data,
    error::{Error, Result},
    http::Http,
    install,
    io::Io,
    store,
    transfer::{Directory, Source},
};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
};
use thereabouts_cli_core::transport::{
    DEFAULT_RELEASE_URL, GITHUB_API_URL, GITHUB_API_VARIABLE, TOKEN_VARIABLES,
};
use thereabouts_core::format::{manifest, verify};

pub(crate) fn source(explicit: Option<&str>, io: &dyn Io) -> Result<Box<dyn Source>> {
    let configured = io.env("THEREABOUTS_RELEASE_URL");
    let value = explicit
        .or(configured.as_deref())
        .unwrap_or(DEFAULT_RELEASE_URL);
    if value.starts_with("http://") || value.starts_with("https://") {
        // A token reads private GitHub releases through the API; it goes nowhere else.
        let token = TOKEN_VARIABLES
            .iter()
            .find_map(|name| io.env(name).filter(|v| !v.is_empty()));
        let api = io
            .env(GITHUB_API_VARIABLE)
            .unwrap_or_else(|| GITHUB_API_URL.into());
        Ok(Box::new(Http::new(value, token, &api)?))
    } else {
        Ok(Box::new(Directory::new(Path::new(value))))
    }
}
fn paths(root: &Path) -> Result<Vec<PathBuf>> {
    let mut paths = Vec::new();
    for family in store::FAMILIES {
        let base = manifest::artifact_path(root, &format!("packs/{family}"))?;
        if !base.exists() {
            continue;
        }
        for item in fs::read_dir(&base)? {
            let item = item?;
            if item.file_type()?.is_symlink() {
                return Err(Error::Integrity("Symlink installation directory".into()));
            }
            if !item.file_type()?.is_dir() {
                continue;
            }
            let path = item.path();
            if path.join("manifest.json").exists() {
                paths.push(path);
            } else {
                // Existing installations have v-<version>/<manifest-digest>/.
                for nested in fs::read_dir(path)? {
                    let nested = nested?;
                    if nested.file_type()?.is_symlink() {
                        return Err(Error::Integrity("Symlink installation directory".into()));
                    }
                    if nested.file_type()?.is_dir() && nested.path().join("manifest.json").exists()
                    {
                        paths.push(nested.path());
                    }
                }
            }
        }
    }
    paths.sort();
    Ok(paths)
}
pub(crate) fn list(root: &Path) -> Result<Value> {
    let mut packs = Vec::new();
    for path in paths(root)? {
        let info = inspect(root, &path, false)?;
        let active = match store::installed(root, &info.family) {
            Ok(selected) => selected == path,
            Err(Error::Missing(_)) => false,
            Err(e) => return Err(e),
        };
        packs.push(
            json!({"family":info.family,"data_version":info.data_version,
            "path":path,"active":active,"format_minor":info.format_minor}),
        );
    }
    Ok(json!({"packs":packs}))
}
pub(crate) fn info(root: &Path) -> Result<Value> {
    let packs = store::inventory(root)?;
    if packs.is_empty() {
        return Err(Error::Missing("core".into()));
    }
    Ok(json!({"client_version":env!("CARGO_PKG_VERSION"),
        "packs":packs.into_iter().map(|(_,m)|m).collect::<Vec<_>>()}))
}
pub(crate) fn run(command: &Data, root: &Path, no_input: bool, io: &mut dyn Io) -> Result<Value> {
    match command {
        Data::Path => Ok(json!({"path":root})),
        Data::List { remote: false } => list(root),
        Data::List { remote: true } => Ok(serde_json::to_value(install::index(
            source(None, io)?.as_ref(),
        )?)?),
        Data::Install {
            packs,
            version,
            source: origin,
            yes: _,
        } => {
            let pin = install::install(
                root,
                source(origin.as_deref(), io)?.as_ref(),
                packs,
                version.as_deref(),
            )?;
            Ok(json!({"installed":pin}))
        }
        Data::Verify { full } => {
            let paths = paths(root)?;
            if paths.is_empty() {
                return Err(Error::Missing("core".into()));
            }
            for path in &paths {
                inspect(root, path, *full)?;
            }
            // Also check pointer integrity; orphan directories need not be active.
            store::inventory(root)?;
            Ok(json!({"verified":if *full {"full"} else {"inventory"},"packs":paths.len()}))
        }
        Data::Remove { pack, yes } => {
            store::family(pack)?;
            if !*yes {
                if no_input || !io.stdin_tty() {
                    return Err(Error::Usage(
                        "data remove requires --yes when input is disabled or not a TTY".into(),
                    ));
                }
                io.stderr(&format!("Remove all installed {pack} packs? [y/N] "))?;
                let mut answer = String::new();
                io.read_line(&mut answer)?;
                if !matches!(answer.trim().to_ascii_lowercase().as_str(), "y" | "yes") {
                    return Err(Error::Usage("Removal cancelled".into()));
                }
            }
            store::remove(root, pack)?;
            Ok(json!({"removed":pack}))
        }
        Data::Update { check: _ } => {
            let pin = store::active(root)?;
            let installed = store::inventory(root)?;
            let families: Vec<String> = if installed.is_empty() {
                vec!["core".into()]
            } else {
                installed.iter().map(|(_, m)| m.family.clone()).collect()
            };
            let current = pin
                .map(|p| p.data_version)
                .or_else(|| installed.first().map(|(_, m)| m.data_version.clone()));
            let index = install::index(source(None, io)?.as_ref())?;
            let (newest, _) = index.select(&families, None)?;
            Ok(json!({"active_version":current,"available_version":newest,
                "update_available":current.as_deref().is_none_or(|v| crate::index::compare_versions(newest,v).is_gt())}))
        }
    }
}

fn inspect(root: &Path, path: &Path, full: bool) -> Result<manifest::Manifest> {
    let family = path
        .strip_prefix(root)
        .ok()
        .and_then(|p| p.components().nth(1))
        .and_then(|c| c.as_os_str().to_str())
        .unwrap_or("core");
    (if full {
        verify::verify(path)
    } else {
        manifest::read(path)
    })
    .map_err(Error::from)
    .map_err(|e| e.at_pack(path, family))
}
