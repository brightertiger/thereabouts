//! Store path policy shared by Python/native and Node; hosts assemble platform paths.
use crate::error::{Error, Result};

/// Resolve explicit, environment and platform defaults without filesystem access.
/// Components let the host retain native separators, including Windows paths under WASM.
pub fn components(
    explicit: Option<&str>,
    platform: &str,
    env: impl Fn(&str) -> Option<String>,
) -> Result<Vec<String>> {
    let configured = env("THEREABOUTS_DATA").filter(|s| !s.is_empty());
    if let Some(path) = explicit.or(configured.as_deref()) {
        let tail = path.strip_prefix("~/").or_else(|| {
            if matches!(platform, "win32" | "windows") {
                path.strip_prefix("~\\")
            } else {
                None
            }
        });
        if path == "~" || tail.is_some() {
            let home = env("HOME")
                .filter(|s| !s.is_empty())
                .or_else(|| env("USERPROFILE").filter(|s| !s.is_empty()))
                .ok_or_else(|| Error::Usage("Cannot expand home directory".into()))?;
            return Ok(vec![home, tail.unwrap_or_default().into()]);
        }
        return Ok(vec![path.into()]);
    }
    platform_components(platform, env)
}
/// Defaults match platformdirs with appauthor disabled; environment access stays injectable.
pub fn platform_components(
    platform: &str,
    env: impl Fn(&str) -> Option<String>,
) -> Result<Vec<String>> {
    let home = || {
        env("HOME")
            .filter(|s| !s.is_empty())
            .ok_or_else(|| Error::Usage("Set THEREABOUTS_DATA or HOME".into()))
    };
    Ok(match platform {
        "darwin" | "macos" => vec![
            home()?,
            "Library".into(),
            "Application Support".into(),
            "Thereabouts".into(),
        ],
        "win32" | "windows" => vec![
            env("LOCALAPPDATA")
                .filter(|s| !s.is_empty())
                .ok_or_else(|| Error::Usage("Set THEREABOUTS_DATA or LOCALAPPDATA".into()))?,
            "Thereabouts".into(),
        ],
        _ => {
            if let Some(base) = env("XDG_DATA_HOME").filter(|s| !s.is_empty()) {
                vec![base, "thereabouts".into()]
            } else {
                vec![
                    home()?,
                    ".local".into(),
                    "share".into(),
                    "thereabouts".into(),
                ]
            }
        }
    })
}
