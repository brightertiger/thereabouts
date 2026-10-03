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
