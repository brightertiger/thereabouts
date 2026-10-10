//! HTTP transfers retain identity bytes and validate every resumed range.
//!
//! Redirects are followed here, at most five: HTTPS anywhere, plain HTTP only between
//! loopback addresses, never HTTPS to HTTP, and every hop repeats the Range header.
//! With a release token and a GitHub release URL, the index and archives are read
//! through the GitHub API (private repositories serve no public download URL); the
//! token is sent only to the API origin, so it never follows a download to GitHub's
//! object host or to any URL an index names.
use crate::{
    error::{Error, Result},
    index::MAX_METADATA_BYTES,
    transfer::{Locator, Source},
};
use serde_json::Value;
use std::{io::Read, net::IpAddr, path::Path, time::Duration};
use thereabouts_cli_core::transport::GITHUB_API_VERSION;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(30);
const HEADER_TIMEOUT: Duration = Duration::from_secs(30);
const READ_STALL_TIMEOUT: Duration = Duration::from_secs(60);
const MAX_REDIRECTS: usize = 5;
const BINARY: &str = "application/octet-stream";
const API_JSON: &str = "application/vnd.github+json";
const INDEX: &str = "index.json";
const ASSET_PAGES: u32 = 10;

/// Token mode: one GitHub release, read through the API.
struct Github {
    api: String,
    repository: String,
    /// `latest` or `tags/<tag>`.
    release: String,
    token: String,
}
pub(crate) struct Http {
    base: String,
    agent: ureq::Agent,
    github: Option<Github>,
}
impl Http {
    /// `token` is used only when `base` is a GitHub release download URL.
    pub fn new(base: &str, token: Option<String>, api: &str) -> Result<Self> {
        let mut http = Self::with_stall(base, READ_STALL_TIMEOUT, ureq::Proxy::try_from_env())?;
        if let Some(token) = token.filter(|t| !t.is_empty()) {
            http.github = github(&http.base, api, token)?;
        }
        Ok(http)
    }
    fn with_stall(base: &str, stall: Duration, proxy: Option<ureq::Proxy>) -> Result<Self> {
        use ureq::unversioned::{
            resolver::DefaultResolver,
            transport::{Connector, DefaultConnector},
        };
        let base = base.trim_end_matches('/');
        validate_url(base)?;
        let config = ureq::Agent::config_builder()
            .proxy(proxy)
            .max_redirects(0)
            .timeout_connect(Some(CONNECT_TIMEOUT))
            .timeout_recv_response(Some(HEADER_TIMEOUT))
            .timeout_send_request(Some(HEADER_TIMEOUT))
            .build();
        Ok(Self {
            base: base.into(),
            agent: ureq::Agent::with_parts(
                config,
                DefaultConnector::default().chain(crate::read_timeout::Stall(stall)),
                DefaultResolver::default(),
            ),
            github: None,
        })
    }
    fn url(&self, name: &str) -> Result<String> {
        if name.starts_with("http://") || name.starts_with("https://") {
            validate_url(name)?;
            if self.base.starts_with("https://") && !name.starts_with("https://") {
                return Err(Error::Integrity("Unsafe archive URL".into()));
            }
            Ok(name.into())
        } else {
            thereabouts_core::format::manifest::artifact_path(Path::new(""), name)?;
            Ok(format!("{}/{name}", self.base))
        }
    }
    /// GET with redirects followed by hand; credentials only for the API origin.
    fn get(
        &self,
        url: &str,
        offset: Option<u64>,
        accept: Option<&str>,
    ) -> Result<ureq::http::Response<ureq::Body>> {
        let mut current = url.to_owned();
        for hop in 0..=MAX_REDIRECTS {
            let mut request = self
                .agent
                .get(&current)
                .config()
                .https_only(current.starts_with("https://"))
                .max_redirects(0)
                .build()
                .header("Accept-Encoding", "identity");
            if let Some(offset) = offset {
                request = request.header("Range", format!("bytes={offset}-"));
            }
            if let Some(accept) = accept {
                request = request.header("Accept", accept);
            }
            if let Some(github) = &self.github
                && same_origin(&current, &github.api)
            {
                request = request
                    .header("Authorization", format!("Bearer {}", github.token))
                    .header("X-GitHub-Api-Version", GITHUB_API_VERSION);
            }
            let response = request.call().map_err(|e| {
                if matches!(e, ureq::Error::StatusCode(_)) {
                    Error::Integrity(format!("Download failed: {e}"))
                } else {
                    Error::download_interrupted(e)
                }
            })?;
            if matches!(response.status().as_u16(), 301 | 302 | 303 | 307 | 308) {
                let location = response
                    .headers()
                    .get("location")
                    .and_then(|v| v.to_str().ok())
                    .ok_or_else(|| Error::Integrity("HTTP redirect without a location".into()))?;
                if hop == MAX_REDIRECTS {
                    break;
                }
                current = next_hop(&current, location)?;
                continue;
            }
            if response
                .headers()
                .get("content-encoding")
                .is_some_and(|v| v != "identity")
            {
                return Err(Error::Integrity(
                    "Encoded transfer would change archive byte identity".into(),
                ));
            }
            return Ok(response);
        }
        Err(Error::Integrity("Unsafe or excessive HTTP redirect".into()))
    }
    /// A bounded metadata document: an index, a release or an asset listing.
    fn metadata(&self, url: &str, accept: Option<&str>) -> Result<Vec<u8>> {
        let response = self.get(url, None, accept)?;
        if response.status() != 200 {
            return Err(Error::Integrity("Release index requires HTTP 200".into()));
        }
        let mut bytes = Vec::new();
        response
            .into_body()
            .into_reader()
            .take(MAX_METADATA_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(Error::download_interrupted)?;
        if bytes.len() as u64 > MAX_METADATA_BYTES {
            return Err(Error::Integrity("Release index exceeds 16 MiB".into()));
        }
        Ok(bytes)
    }
    /// The index asset's id: listed in the release, or on one of its asset pages.
    fn index_asset(&self, github: &Github, release: &Value) -> Result<u64> {
        let named = |assets: &Value| {
            assets.as_array().and_then(|items| {
                items
                    .iter()
                    .find(|a| a["name"] == INDEX)
                    .and_then(|a| a["id"].as_u64())
            })
        };
        if let Some(id) = named(&release["assets"]) {
            return Ok(id);
        }
        let release_id = release["id"]
            .as_u64()
            .ok_or_else(|| Error::Integrity("Invalid GitHub release response".into()))?;
        for page in 1..=ASSET_PAGES {
            let url = format!(
                "{}/repos/{}/releases/{release_id}/assets?per_page=100&page={page}",
                github.api, github.repository
            );
            let assets: Value = serde_json::from_slice(&self.metadata(&url, Some(API_JSON))?)?;
            if let Some(id) = named(&assets) {
                return Ok(id);
            }
            if assets.as_array().is_none_or(|items| items.len() < 100) {
                break;
            }
        }
        Err(Error::Integrity(
            "The GitHub release has no index.json".into(),
        ))
    }
    fn transfer(
        &self,
        url: &str,
        accept: Option<&str>,
        offset: u64,
        total: u64,
    ) -> Result<Box<dyn Read>> {
        if offset >= total {
            return Err(Error::Integrity("Invalid resume offset".into()));
        }
        let response = self.get(url, (offset > 0).then_some(offset), accept)?;
        let status = response.status().as_u16();
        if offset > 0 {
            let expected = format!("bytes {offset}-{}/{total}", total - 1);
            if status != 206
                || response
                    .headers()
                    .get("content-range")
                    .and_then(|h| h.to_str().ok())
                    != Some(expected.as_str())
            {
                return Err(Error::Integrity(
                    "Server did not honor the exact resume range; partial download retained".into(),
                ));
            }
        } else if status != 200 {
            return Err(Error::Integrity(
                "Initial archive transfer requires HTTP 200".into(),
            ));
        }
        if let Some(length) = response.headers().get("content-length")
            && length.to_str().ok().and_then(|v| v.parse::<u64>().ok()) != Some(total - offset)
        {
            return Err(Error::Integrity(
                "HTTP archive length differs from release index".into(),
            ));
        }
        Ok(Box::new(response.into_body().into_reader()))
    }
}
fn validate_url(value: &str) -> Result<()> {
    let uri: ureq::http::Uri = value
        .parse()
        .map_err(|_| Error::Usage("Invalid release URL".into()))?;
    if !matches!(uri.scheme_str(), Some("http" | "https"))
        || uri.host().is_none()
        || uri.authority().is_some_and(|a| a.as_str().contains('@'))
        || value.contains('#')
    {
        return Err(Error::Usage(
            "Use an HTTP(S) release URL without credentials or fragment".into(),
        ));
    }
    Ok(())
}
fn loopback(host: &str) -> bool {
    host == "localhost"
        || host
            .trim_start_matches('[')
            .trim_end_matches(']')
            .parse::<IpAddr>()
            .is_ok_and(|ip| ip.is_loopback())
}
/// Scheme, host and port, with default ports filled in.
fn origin(url: &str) -> Option<(String, String, u16)> {
    let uri: ureq::http::Uri = url.parse().ok()?;
    let scheme = uri.scheme_str()?.to_ascii_lowercase();
    let port = uri
        .port_u16()
        .unwrap_or(if scheme == "https" { 443 } else { 80 });
    Some((scheme, uri.host()?.to_ascii_lowercase(), port))
}
fn same_origin(a: &str, b: &str) -> bool {
    origin(a).is_some_and(|left| origin(b).is_some_and(|right| left == right))
}
/// The next URL of a redirect: HTTPS, or plain HTTP from loopback to loopback.
fn next_hop(current: &str, location: &str) -> Result<String> {
    let target = if location.starts_with("https://") || location.starts_with("http://") {
        location.to_owned()
    } else if location.starts_with('/') && !location.starts_with("//") {
        let uri: ureq::http::Uri = current
            .parse()
            .map_err(|_| Error::Integrity("Invalid redirect".into()))?;
        let (Some(scheme), Some(authority)) = (uri.scheme_str(), uri.authority()) else {
            return Err(Error::Integrity("Invalid redirect".into()));
        };
        format!("{scheme}://{authority}{location}")
    } else {
        return Err(Error::Integrity(
            "Unsupported HTTP redirect location".into(),
        ));
    };
    validate_url(&target).map_err(|_| Error::Integrity("Invalid redirect target".into()))?;
    let host = target
        .parse::<ureq::http::Uri>()
        .ok()
        .and_then(|u| u.host().map(str::to_owned))
        .unwrap_or_default();
    if target.starts_with("https://")
        || (current.starts_with("http://") && target.starts_with("http://") && loopback(&host))
    {
        Ok(target)
    } else {
        Err(Error::Integrity("Unsafe or excessive HTTP redirect".into()))
    }
}
/// Token mode for `<host>/<owner>/<repo>/releases/latest/download` or
/// `.../releases/download/<tag>`; any other release URL never sees the token.
fn github(base: &str, api: &str, token: String) -> Result<Option<Github>> {
    let uri: ureq::http::Uri = base
        .parse()
        .map_err(|_| Error::Usage("Invalid release URL".into()))?;
    let parts: Vec<&str> = uri.path().trim_matches('/').split('/').collect();
    let (owner, name, release) = match parts.as_slice() {
        [owner, name, "releases", "latest", "download"] => (owner, name, "latest".to_owned()),
        [owner, name, "releases", "download", tag] if !tag.is_empty() => {
            (owner, name, format!("tags/{tag}"))
        }
        _ => return Ok(None),
    };
    let api = api.trim_end_matches('/');
    let host = origin(api).map(|(_, host, _)| host).unwrap_or_default();
    if validate_url(api).is_err() || !(api.starts_with("https://") || loopback(&host)) {
        return Err(Error::Usage(
            "THEREABOUTS_GITHUB_API_URL must be an HTTPS URL (plain HTTP only on loopback)".into(),
        ));
    }
    Ok(Some(Github {
        api: api.into(),
        repository: format!("{owner}/{name}"),
        release,
        token,
    }))
}
impl Source for Http {
    fn origin(&self) -> Option<String> {
        Some(self.base.clone())
    }
    fn index(&self) -> Result<Vec<u8>> {
        let Some(github) = &self.github else {
            return self.metadata(&format!("{}/{INDEX}", self.base), None);
        };
        let url = format!(
            "{}/repos/{}/releases/{}",
            github.api, github.repository, github.release
        );
        let release: Value = serde_json::from_slice(&self.metadata(&url, Some(API_JSON))?)?;
        let id = self.index_asset(github, &release)?;
        let url = format!(
            "{}/repos/{}/releases/assets/{id}",
            github.api, github.repository
        );
        self.metadata(&url, Some(BINARY))
    }
    fn open(&self, name: &str, offset: u64, total: u64) -> Result<Box<dyn Read>> {
        self.transfer(&self.url(name)?, None, offset, total)
    }
    fn open_file(&self, file: Locator<'_>, offset: u64, total: u64) -> Result<Box<dyn Read>> {
        if let (Some(github), Some(api_url)) = (&self.github, file.api_url)
            && same_origin(api_url, &github.api)
        {
            validate_url(api_url)?;
            return self.transfer(api_url, Some(BINARY), offset, total);
        }
        self.open(file.url, offset, total)
    }
}

#[cfg(test)]
mod tests;
