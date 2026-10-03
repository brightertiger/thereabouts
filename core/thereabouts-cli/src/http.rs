//! HTTP transfers retain identity bytes and validate every resumed range.
use crate::{
    error::{Error, Result},
    transfer::Source,
};
use std::{io::Read, path::Path, time::Duration};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(30);
const HEADER_TIMEOUT: Duration = Duration::from_secs(30);
const READ_STALL_TIMEOUT: Duration = Duration::from_secs(60);

pub(crate) struct Http {
    base: String,
    agent: ureq::Agent,
}
impl Http {
    pub fn new(base: &str) -> Result<Self> {
        Self::with_stall(base, READ_STALL_TIMEOUT)
    }
    fn with_stall(base: &str, stall: Duration) -> Result<Self> {
        use ureq::unversioned::{
            resolver::DefaultResolver,
            transport::{Connector, DefaultConnector},
        };
        let base = base.trim_end_matches('/');
        validate_url(base)?;
        let config = ureq::Agent::config_builder()
            .proxy(None)
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
        })
    }
    fn url(&self, name: &str) -> Result<String> {
        if name.starts_with("http://") || name.starts_with("https://") {
            validate_url(name)?;
            Ok(name.into())
        } else {
            thereabouts_core::format::manifest::artifact_path(Path::new(""), name)?;
            Ok(format!("{}/{name}", self.base))
        }
    }
    fn get(&self, url: &str, offset: Option<u64>) -> Result<ureq::http::Response<ureq::Body>> {
        let mut request = self.agent.get(url).header("Accept-Encoding", "identity");
        if let Some(offset) = offset {
            request = request.header("Range", format!("bytes={offset}-"));
        }
        let response = request
            .call()
            .map_err(|e| Error::Integrity(format!("Download failed: {e}")))?;
        if response
            .headers()
            .get("content-encoding")
            .is_some_and(|v| v != "identity")
        {
            return Err(Error::Integrity(
                "Encoded transfer would change archive byte identity".into(),
            ));
        }
        Ok(response)
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
impl Source for Http {
    fn index(&self) -> Result<Vec<u8>> {
        let response = self.get(&format!("{}/index.json", self.base), None)?;
        if response.status() != 200 {
            return Err(Error::Integrity("Release index requires HTTP 200".into()));
        }
        let mut bytes = Vec::new();
        response
            .into_body()
            .into_reader()
            .take(16 * 1024 * 1024 + 1)
            .read_to_end(&mut bytes)?;
        if bytes.len() > 16 * 1024 * 1024 {
            return Err(Error::Integrity("Release index exceeds 16 MiB".into()));
        }
        Ok(bytes)
    }
    fn open(&self, name: &str, offset: u64, total: u64) -> Result<Box<dyn Read>> {
        if offset >= total {
            return Err(Error::Integrity("Invalid resume offset".into()));
        }
        let response = self.get(&self.url(name)?, (offset > 0).then_some(offset))?;
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{BufRead, BufReader, Write},
        net::TcpListener,
        thread,
    };
    #[test]
    fn steady_transfer_outlives_a_stall_budget_and_a_stalled_body_fails() {
        for stalled in [false, true] {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let base = format!("http://{}", listener.local_addr().unwrap());
            let server = thread::spawn(move || {
                let (mut stream, _) = listener.accept().unwrap();
                let mut reader = BufReader::new(stream.try_clone().unwrap());
                loop {
                    let mut line = String::new();
                    reader.read_line(&mut line).unwrap();
                    if line == "\r\n" {
                        break;
                    }
                }
                stream
                    .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\n")
                    .unwrap();
                for _ in 0..8 {
                    thread::sleep(Duration::from_millis(if stalled { 250 } else { 25 }));
                    if stream.write_all(b"x").is_err() {
                        break;
                    }
                }
            });
            let client = Http::with_stall(&base, Duration::from_millis(100)).unwrap();
            let mut bytes = Vec::new();
            let result = client
                .open("pack.tar", 0, 8)
                .unwrap()
                .read_to_end(&mut bytes);
            if stalled {
                assert!(result.is_err());
            } else {
                assert_eq!(bytes, b"xxxxxxxx");
            }
            server.join().unwrap();
        }
    }
}
