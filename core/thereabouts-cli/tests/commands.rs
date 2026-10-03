//! The command grammar runs through injected IO, independent of process globals.
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]
mod support;
use serde_json::Value;
use std::{fs, io::Cursor};
use support::{Host, install};

#[test]
fn every_lookup_supports_tty_tables_and_piped_json() {
    let temp = tempfile::tempdir().unwrap();
    install(
        temp.path(),
        &[
            "core", "postal", "airports", "locode", "phone", "ip", "plates",
        ],
    );
    let mut host = Host::new(temp.path());
    let commands: Vec<Vec<&str>> = vec![
        vec!["reverse", "--lat", "48.8566", "--lon", "2.3522"],
        vec!["h3", "881fb46625fffff"],
        vec!["geocode", "Paris", "--country", "FR"],
        vec!["postal", "75001", "--country", "FR"],
        vec!["airport", "CDG"],
        vec!["locode", "BEANR"],
        vec!["phone", "+3225551234"],
        vec!["ip", "8.8.8.8"],
        vec!["plate", "AB-123-CD", "--country", "FR"],
    ];
    for command in commands {
        host.tty = false;
        assert_eq!(host.run(&command), 0, "{}", host.err);
        let json: Value = serde_json::from_str(&host.out).unwrap();
        assert!(json["status"].is_string());
        host.tty = true;
        assert_eq!(host.run(&command), 0, "{}", host.err);
        assert!(host.out.contains("status") && host.out.contains(" | "));
        assert!(!host.out.contains('\x1b'));
    }
}
#[test]
fn formats_fields_evidence_help_and_all_exit_codes() {
    let temp = tempfile::tempdir().unwrap();
    let mut host = Host::new(temp.path());
    assert_eq!(host.run(&["--version"]), 0);
    assert_eq!(host.run(&["--fields"]), 0);
    assert!(host.out.lines().any(|s| s == "city.name"));
    assert_eq!(host.run(&["geocode", "--help"]), 0);
    assert!(
        host.out
            .starts_with("Finds towns and cities by name. Street addresses are not supported.")
    );
    assert_eq!(host.run(&["postal", "75001"]), 2);
    assert_eq!(host.run(&["reverse", "--lat", "0", "--lon", "0"]), 3);
    assert_eq!(
        host.err,
        "core data is not installed. Install it with:\nthereabouts data install core\n"
    );
    install(temp.path(), &["core"]);
    assert_eq!(host.run(&["reverse", "--lat", "91", "--lon", "0"]), 2);
    assert_eq!(
        host.run(&["reverse", "--lat", "0", "--lon", "0", "--strict"]),
        1
    );
    assert_eq!(
        host.run(&[
            "reverse",
            "--lat",
            "48.8566",
            "--lon",
            "2.3522",
            "--json",
            "--evidence"
        ]),
        0
    );
    let value: Value = serde_json::from_str(&host.out).unwrap();
    assert!(value.get("evidence").is_some() && host.out.lines().count() > 2);
    assert_eq!(
        host.run(&[
            "h3",
            "881fb46625fffff",
            "--fields",
            "status,country.code",
            "--csv"
        ]),
        0
    );
    assert_eq!(host.out.lines().next().unwrap(), "status,country.code");
    assert_eq!(host.run(&["h3", "bad", "--fields", "imaginary"]), 2);
    assert_eq!(host.run(&["info", "--json", "--csv"]), 2);
    host.input = Cursor::new(b"lat,lon\n0,0\n91,0\n".to_vec());
    assert_eq!(host.run(&["reverse", "-"]), 5);
    fs::write(temp.path().join("active.json"), "bad").unwrap();
    assert_eq!(host.run(&["reverse", "--lat", "0", "--lon", "0"]), 4);
}
#[test]
fn data_inventory_verify_path_and_removal_prompts() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    for args in [
        vec!["info"],
        vec!["data", "list"],
        vec!["data", "verify"],
        vec!["data", "verify", "--full"],
        vec!["data", "path"],
    ] {
        assert_eq!(host.run(&args), 0, "{}", host.err);
        let _: Value = serde_json::from_str(&host.out).unwrap();
        host.tty = true;
        assert_eq!(host.run(&args), 0);
        assert!(!host.out.contains('\x1b'));
        host.tty = false;
    }
    assert_eq!(host.run(&["data", "remove", "core"]), 2);
    host.tty = true;
    host.input = Cursor::new(b"no\n".to_vec());
    assert_eq!(host.run(&["data", "remove", "core"]), 2);
    assert!(host.err.contains("[y/N]"));
    host.input = Cursor::new(b"yes\n".to_vec());
    assert_eq!(host.run(&["data", "remove", "core", "--no-input"]), 2);
    assert_eq!(host.run(&["data", "remove", "core"]), 0);
    assert_eq!(host.run(&["data", "verify"]), 3);
    assert_eq!(host.run(&["data", "remove", "core", "--yes"]), 0);
}
#[test]
fn csv_and_ndjson_preserve_inputs_and_continue_after_bad_rows() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    host.input = Cursor::new(
        b"id,latitude,lng,note\n1,48.8566,2.3522,\"a,b\"\n2,bad,0,wrong\n3,0,0,\"two\nlines\"\n"
            .to_vec(),
    );
    assert_eq!(
        host.run(&["reverse", "-", "--csv", "--fields", "status,country.code"]),
        5,
        "{}",
        host.err
    );
    let mut csv = csv::Reader::from_reader(host.out.as_bytes());
    let headers = csv.headers().unwrap().clone();
    let rows = csv
        .records()
        .collect::<std::result::Result<Vec<_>, _>>()
        .unwrap();
    assert_eq!(rows.len(), 3);
    let note = headers.iter().position(|s| s == "note").unwrap();
    assert_eq!(&rows[0][note], "a,b");
    assert_eq!(&rows[2][note], "two\nlines");
    assert!(host.out.contains("invalid_input"));
    host.input = Cursor::new(
        b"{\"lat\":48.8566,\"lon\":2.3522,\"id\":7}\nbad\n{\"lat\":0,\"lon\":0,\"id\":9}\n"
            .to_vec(),
    );
    assert_eq!(host.run(&["reverse", "-", "--json"]), 5);
    let value: Value = serde_json::from_str(&host.out).unwrap();
    assert_eq!(value["results"][0]["id"], 7);
    assert_eq!(value["results"][1]["thereabouts_status"], "invalid_input");
    assert_eq!(value["results"][2]["id"], 9);
    host.input = Cursor::new(b"north,east\n0,0\n".to_vec());
    assert_eq!(
        host.run(&["reverse", "-", "--lat-col", "north", "--lon-col", "east"]),
        0
    );
    host.input = Cursor::new(b"north,east\n0,0\n".to_vec());
    assert_eq!(host.run(&["reverse", "-"]), 2);
}

#[test]
fn release_install_remote_list_and_update_use_explicit_sources() {
    let temp = tempfile::tempdir().unwrap();
    let release = temp.path().join("release");
    support::release(&release);
    let store = temp.path().join("store");
    let mut host = Host::new(&store);
    host.env.insert(
        "THEREABOUTS_RELEASE_URL".into(),
        release.to_str().unwrap().into(),
    );
    for tty in [false, true] {
        host.tty = tty;
        assert_eq!(host.run(&["data", "list", "--remote"]), 0, "{}", host.err);
        assert_eq!(
            host.run(&["data", "install", "phone", "--version", "2026.10", "--yes"]),
            0,
            "{}",
            host.err
        );
        assert_eq!(host.run(&["data", "update", "--check"]), 0, "{}", host.err);
    }
    host.tty = false;
    assert_eq!(host.run(&["data", "update"]), 2);
    assert_eq!(host.run(&["data", "update", "--check"]), 0);
    let value: Value = serde_json::from_str(&host.out).unwrap();
    assert_eq!(value["update_available"], false);
    assert_eq!(host.run(&["phone", "+32", "--country", "BE"]), 0);
    assert_eq!(
        host.run(&["phone", "+32", "--country", "US", "--strict"]),
        1
    );
    assert_eq!(host.run(&["phone", "+32", "--country", "Belgium"]), 2);
}

#[test]
fn tabular_ndjson_keeps_union_columns_and_initial_failures() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    host.input = Cursor::new(
        b"{bad}\n{\"lat\":0,\"lon\":0,\"id\":7}\n{\"lat\":91,\"lon\":0,\"tag\":\"x\"}\n".to_vec(),
    );
    assert_eq!(host.run(&["reverse", "-", "--csv"]), 5, "{}", host.err);
    let mut csv = csv::Reader::from_reader(host.out.as_bytes());
    let headers = csv.headers().unwrap().clone();
    assert!(headers.iter().any(|s| s == "id"));
    assert!(headers.iter().any(|s| s == "tag"));
    assert!(headers.iter().any(|s| s == "thereabouts_hint"));
    assert_eq!(csv.records().count(), 3);
    host.input = Cursor::new(b"lat,lon\n48.8566,2.3522\n91,0\n".to_vec());
    assert_eq!(host.run(&["reverse", "-", "--csv"]), 5, "{}", host.err);
}

#[test]
fn verify_checks_sizes_by_default_and_content_with_full() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let pack = thereabouts_cli::store::installed(temp.path(), "core").unwrap();
    let manifest = thereabouts_core::format::manifest::read(&pack).unwrap();
    let notice = manifest.files.iter().find(|f| f.kind == "notice").unwrap();
    let path = pack.join(&notice.path);
    let mut bytes = fs::read(&path).unwrap();
    bytes[0] ^= 1;
    fs::write(&path, &bytes).unwrap();
    assert_eq!(host.run(&["data", "verify"]), 0);
    assert_eq!(host.run(&["data", "verify", "--full"]), 4);
    bytes.push(0);
    fs::write(path, bytes).unwrap();
    assert_eq!(host.run(&["data", "verify"]), 4);
}

#[test]
fn help_explains_globals_and_reverse_alternatives() {
    let temp = tempfile::tempdir().unwrap();
    let mut host = Host::new(temp.path());
    assert_eq!(host.run(&[]), 2);
    assert_eq!(host.out, "");
    assert!(host.err.contains("Usage:"));
    assert_eq!(host.run(&["reverse", "--help"]), 0);
    assert!(host.out.contains("reverse --lat LAT --lon LON"));
    assert!(host.out.contains("reverse FILE|-"));
    for explanation in [
        "installed data store",
        "pretty JSON",
        "input columns",
        "source and method",
        "progress",
        "interactive confirmation",
        "no match",
    ] {
        assert!(host.out.contains(explanation), "{explanation}");
    }
}

#[test]
fn one_column_input_is_usage_but_bad_ndjson_rows_continue() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    for input in ["lat\n48\n", "lat;lon\n48;2\n"] {
        host.input = Cursor::new(input.as_bytes().to_vec());
        assert_eq!(host.run(&["reverse", "-"]), 2);
        assert!(host.err.contains("comma-separated CSV"));
    }
    host.input = Cursor::new(b"{bad}\n{\"lat\":95,\"lon\":0}\n".to_vec());
    assert_eq!(host.run(&["reverse", "-"]), 5);
    let rows: Vec<serde_json::Value> = host
        .out
        .lines()
        .map(|s| serde_json::from_str(s).unwrap())
        .collect();
    assert_eq!(rows.len(), 2);
    assert!(
        rows.last().unwrap()["thereabouts_hint"]
            .as_str()
            .unwrap()
            .contains("[-90, 90]")
    );
}
