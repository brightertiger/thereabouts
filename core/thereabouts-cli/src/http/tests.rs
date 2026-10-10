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
        let client = Http::with_stall(&base, Duration::from_millis(100), None).unwrap();
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
#[test]
fn trusted_loopback_https_redirects_and_downgrades_are_rejected() {
    use rustls::{
        ServerConfig, ServerConnection, StreamOwned,
        pki_types::{CertificateDer, PrivateKeyDer, PrivatePkcs8KeyDer},
    };
    use std::sync::Arc;
    let cert = include_bytes!("../../tests/fixtures/localhost.der");
    let key = include_bytes!("../../tests/fixtures/localhost-key.der");
    let config = Arc::new(
        ServerConfig::builder()
            .with_no_client_auth()
            .with_single_cert(
                vec![CertificateDer::from(cert.to_vec())],
                PrivateKeyDer::Pkcs8(PrivatePkcs8KeyDer::from(key.to_vec())),
            )
            .unwrap(),
    );
    for downgrade in [false, true] {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let base = format!("https://{address}");
        let tls = Arc::clone(&config);
        let server = thread::spawn(move || {
            for index in 0..if downgrade { 1 } else { 2 } {
                let (stream, _) = listener.accept().unwrap();
                stream
                    .set_read_timeout(Some(Duration::from_secs(5)))
                    .unwrap();
                let mut stream =
                    StreamOwned::new(ServerConnection::new(Arc::clone(&tls)).unwrap(), stream);
                let mut request = BufReader::new(&mut stream);
                loop {
                    let mut line = String::new();
                    request.read_line(&mut line).unwrap();
                    if line == "\r\n" {
                        break;
                    }
                }
                let response = if index == 0 {
                    format!(
                        "HTTP/1.1 302 Found\r\nLocation: {}://{address}/final\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                        if downgrade { "http" } else { "https" }
                    )
                } else {
                    "HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}".into()
                };
                stream.write_all(response.as_bytes()).unwrap();
                stream.flush().unwrap();
            }
        });
        let mut client = Http::with_stall(&base, Duration::from_secs(2), None).unwrap();
        client.agent = ureq::Agent::config_builder()
            .proxy(None)
            .tls_config(
                ureq::tls::TlsConfig::builder()
                    .root_certs(ureq::tls::RootCerts::new_with_certs(&[
                        ureq::tls::Certificate::from_der(cert),
                    ]))
                    .build(),
            )
            .timeout_connect(Some(Duration::from_secs(2)))
            .build()
            .into();
        let result = client.index();
        if downgrade {
            assert!(result.is_err());
        } else {
            assert_eq!(result.unwrap(), b"{}");
        }
        server.join().unwrap();
    }
}

/// One request as a loopback server saw it.
#[derive(Clone, Debug)]
struct Seen {
    path: String,
    range: Option<String>,
    authorization: Option<String>,
    accept: Option<String>,
}
type Log = std::sync::Arc<std::sync::Mutex<Vec<Seen>>>;
/// Serve every connection with `route`, one request per connection.
fn serve(route: impl Fn(&Seen) -> Vec<u8> + Send + 'static) -> (String, Log) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let log = Log::default();
    let seen = std::sync::Arc::clone(&log);
    thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(mut stream) = stream else { break };
            let mut reader = BufReader::new(stream.try_clone().unwrap());
            let mut line = String::new();
            reader.read_line(&mut line).unwrap();
            let mut request = Seen {
                path: line.split(' ').nth(1).unwrap_or_default().to_owned(),
                range: None,
                authorization: None,
                accept: None,
            };
            loop {
                let mut header = String::new();
                reader.read_line(&mut header).unwrap();
                if header == "\r\n" || header.is_empty() {
                    break;
                }
                let (name, value) = header.trim_end().split_once(": ").unwrap_or_default();
                let value = Some(value.to_owned());
                match name.to_ascii_lowercase().as_str() {
                    "range" => request.range = value,
                    "authorization" => request.authorization = value,
                    "accept" => request.accept = value,
                    _ => {}
                }
            }
            let response = route(&request);
            seen.lock().unwrap().push(request);
            let _ = stream.write_all(&response);
        }
    });
    (base, log)
}
fn redirect(location: &str) -> Vec<u8> {
    format!("HTTP/1.1 302 Found\r\nLocation: {location}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        .into_bytes()
}
fn reply(status: &str, headers: &str, body: &[u8]) -> Vec<u8> {
    let mut response = format!(
        "HTTP/1.1 {status}\r\n{headers}Content-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .into_bytes();
    response.extend_from_slice(body);
    response
}
const DATA: &[u8] = b"0123456789";
/// GitHub's object host: `/1/core.tar.zst` honours Range, `/2/index.json` is the index.
fn objects() -> (String, Log) {
    serve(|seen| match seen.path.as_str() {
        "/1/core.tar.zst" => match &seen.range {
            Some(range) => {
                let offset: usize = range
                    .trim_start_matches("bytes=")
                    .trim_end_matches('-')
                    .parse()
                    .unwrap();
                let headers = format!("Content-Range: bytes {offset}-9/10\r\n");
                reply("206 Partial Content", &headers, DATA.get(offset..).unwrap())
            }
            None => reply("200 OK", "", DATA),
        },
        "/2/index.json" => reply("200 OK", "", b"{}"),
        _ => reply("404 Not Found", "", b""),
    })
}
fn read(mut input: Box<dyn Read>) -> Vec<u8> {
    let mut bytes = Vec::new();
    input.read_to_end(&mut bytes).unwrap();
    bytes
}
#[test]
fn public_downloads_follow_redirects_with_range_and_no_credentials() {
    let (store, store_log) = objects();
    let (web, web_log) = serve(move |seen| match seen.path.as_str() {
        "/o/r/releases/latest/download/index.json" => {
            redirect("/o/r/releases/download/v1/index.json")
        }
        "/o/r/releases/download/v1/index.json" => redirect(&format!("{store}/2/index.json")),
        "/o/r/releases/download/v1/core.tar.zst" => redirect(&format!("{store}/1/core.tar.zst")),
        _ => reply("404 Not Found", "", b""),
    });
    // No token: the API URL in the index is never used.
    let client = Http::new(
        &format!("{web}/o/r/releases/latest/download/"),
        None,
        "https://api.github.invalid",
    )
    .unwrap();
    assert_eq!(client.index().unwrap(), b"{}");
    let url = format!("{web}/o/r/releases/download/v1/core.tar.zst");
    let file = Locator {
        url: &url,
        api_url: Some("https://api.github.invalid/repos/o/r/releases/assets/1"),
    };
    assert_eq!(read(client.open_file(file, 4, 10).unwrap()), b"456789");
    let requests: Vec<Seen> = [web_log, store_log]
        .iter()
        .flat_map(|log| log.lock().unwrap().clone())
        .collect();
    assert!(requests.iter().all(|r| r.authorization.is_none()));
    let ranged: Vec<_> = requests
        .iter()
        .filter(|r| r.path.ends_with("core.tar.zst"))
        .map(|r| r.range.as_deref())
        .collect();
    assert_eq!(ranged, [Some("bytes=4-"), Some("bytes=4-")]);
}
#[test]
fn a_token_reads_through_the_api_and_stays_at_its_origin() {
    let (store, store_log) = objects();
    let (web, web_log) = serve(|_| reply("404 Not Found", "", b""));
    let (api, api_log) = serve(move |seen| {
        if seen.authorization.as_deref() != Some("Bearer secret") {
            return reply("404 Not Found", "", b"");
        }
        match seen.path.as_str() {
            "/repos/o/r/releases/tags/v1" => reply("200 OK", "", br#"{"id":5,"assets":[]}"#),
            "/repos/o/r/releases/5/assets?per_page=100&page=1" => {
                reply("200 OK", "", br#"[{"id":2,"name":"index.json"}]"#)
            }
            "/repos/o/r/releases/assets/2" => redirect(&format!("{store}/2/index.json")),
            "/repos/o/r/releases/assets/1" => redirect(&format!("{store}/1/core.tar.zst")),
            _ => reply("404 Not Found", "", b""),
        }
    });
    let client = Http::new(
        &format!("{web}/o/r/releases/download/v1"),
        Some("secret".into()),
        &api,
    )
    .unwrap();
    assert_eq!(client.index().unwrap(), b"{}");
    let url = format!("{web}/o/r/releases/download/v1/core.tar.zst");
    let api_url = format!("{api}/repos/o/r/releases/assets/1");
    let file = Locator {
        url: &url,
        api_url: Some(&api_url),
    };
    assert_eq!(read(client.open_file(file, 3, 10).unwrap()), b"3456789");
    assert!(web_log.lock().unwrap().is_empty());
    let api_requests = api_log.lock().unwrap().clone();
    assert!(
        api_requests
            .iter()
            .all(|r| r.authorization.as_deref() == Some("Bearer secret"))
    );
    let asset = api_requests
        .iter()
        .find(|r| r.path.ends_with("/assets/1"))
        .unwrap();
    assert_eq!(asset.accept.as_deref(), Some("application/octet-stream"));
    assert_eq!(asset.range.as_deref(), Some("bytes=3-"));
    let objects = store_log.lock().unwrap().clone();
    assert_eq!(objects.len(), 2);
    assert!(objects.iter().all(|r| r.authorization.is_none()));
    // An index may name any API URL; the token goes only to the configured origin.
    let elsewhere = format!("{web}/repos/o/r/releases/assets/1");
    let file = Locator {
        url: &url,
        api_url: Some(&elsewhere),
    };
    assert!(client.open_file(file, 0, 10).is_err());
    assert!(
        web_log
            .lock()
            .unwrap()
            .iter()
            .all(|r| r.authorization.is_none() && r.path.ends_with("core.tar.zst"))
    );
}
#[test]
fn a_token_is_unused_for_other_release_urls() {
    let (mirror, log) = serve(|_| reply("200 OK", "", b"{}"));
    let client = Http::new(&format!("{mirror}/mirror/"), Some("secret".into()), &mirror).unwrap();
    assert_eq!(client.index().unwrap(), b"{}");
    assert!(log.lock().unwrap().first().unwrap().authorization.is_none());
    assert!(
        Http::new(
            "https://github.com/o/r/releases/latest/download/",
            Some("secret".into()),
            "http://api.example.com"
        )
        .is_err()
    );
}
#[test]
fn unsafe_and_excessive_redirects_and_downgraded_entries_are_refused() {
    let (outside, _) = serve(|_| redirect("http://release.invalid/x"));
    let client = Http::with_stall(&outside, Duration::from_secs(2), None).unwrap();
    let error = client.index().unwrap_err().to_string();
    assert!(error.contains("Unsafe or excessive"), "{error}");
    let (looping, log) = serve(|seen| redirect(&format!("{}x", seen.path)));
    let client = Http::with_stall(&looping, Duration::from_secs(2), None).unwrap();
    assert!(client.index().is_err());
    assert_eq!(log.lock().unwrap().len(), MAX_REDIRECTS + 1);
    let secure =
        Http::with_stall("https://release.invalid/r", Duration::from_secs(2), None).unwrap();
    let error = secure
        .open("http://release.invalid/core.tar.zst", 0, 1)
        .err()
        .unwrap()
        .to_string();
    assert!(error.contains("Unsafe archive URL"), "{error}");
}
