//! Human tables and ordered columns are stable parts of the command interface.
#![allow(clippy::unwrap_used)]
mod support;
use std::io::Cursor;
use support::{Host, install};

#[test]
fn tty_summary_has_one_header_no_json_and_indented_candidates() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core", "postal"]);
    let mut host = Host::new(temp.path());
    host.tty = true;
    assert_eq!(
        host.run(&[
            "reverse",
            "--lat",
            "48.8566",
            "--lon",
            "2.3522",
            "--evidence"
        ]),
        0
    );
    let lines: Vec<_> = host.out.lines().collect();
    assert_eq!(lines.len(), 2);
    let headers = lines
        .first()
        .unwrap()
        .split(" | ")
        .map(str::trim)
        .collect::<Vec<_>>();
    assert_eq!(
        headers,
        [
            "status", "country", "state", "city", "timezone", "point", "match"
        ]
    );
    assert!(!host.out.contains(['{', '[', '\x1b']));
    assert!(host.out.contains("Paris"));
    assert_eq!(host.run(&["postal", "744301", "--country", "IN"]), 0);
    assert!(host.out.lines().skip(2).all(|s| s.starts_with("  ")));
    assert!(host.out.lines().count() > 2);
    assert_eq!(host.run(&["h3", "bad", "--fields", "status,city.name"]), 2);
    assert!(host.out.starts_with("status"));
    assert_eq!(
        host.out
            .lines()
            .next()
            .unwrap()
            .split(" | ")
            .map(str::trim)
            .collect::<Vec<_>>(),
        ["status", "city.name"]
    );
    assert_eq!(host.run(&["h3", "bad", "--fields", "evidence"]), 2);
    assert!(host.err.contains("--json --evidence"));
}

#[test]
fn csv_headers_preserve_source_order_then_public_or_selected_result_order() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let input = b"id,Lat,Lon\nq,48.8566,2.3522\nr,no,0\n";
    host.input = Cursor::new(input.to_vec());
    assert_eq!(
        host.run(&[
            "reverse",
            "-",
            "--lat-col",
            "Lat",
            "--lon-col",
            "Lon",
            "--csv"
        ]),
        5
    );
    assert!(host.out.starts_with("id,Lat,Lon,thereabouts_status,thereabouts_kind,thereabouts_match,thereabouts_country,thereabouts_state,thereabouts_city,thereabouts_timezone,thereabouts_point,"));
    host.input = Cursor::new(input.to_vec());
    assert_eq!(
        host.run(&[
            "reverse",
            "-",
            "--lat-col",
            "Lat",
            "--lon-col",
            "Lon",
            "--csv",
            "--fields",
            "status,city.name"
        ]),
        5
    );
    assert_eq!(
        host.out.lines().next().unwrap(),
        "id,Lat,Lon,thereabouts_status,thereabouts_city.name"
    );
}

#[test]
fn table_uses_columns_environment_for_scalar_and_batch() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    host.tty = true;
    host.env.insert("COLUMNS".into(), "80".into());
    assert_eq!(
        host.run(&["reverse", "--lat", "48.8566", "--lon", "2.3522"]),
        0
    );
    assert!(host.out.lines().all(|s| s.chars().count() <= 80));
    host.input = Cursor::new(
        b"id,lat,lon,note\n1,48.8566,2.3522,A long input note that needs truncation\n".to_vec(),
    );
    assert_eq!(host.run(&["reverse", "-"]), 0, "{}", host.err);
    assert!(host.out.lines().all(|s| s.chars().count() <= 80));
    assert!(!host.out.contains("thereabou"));
    assert!(host.out.lines().next().unwrap().contains("timezone"));
}
