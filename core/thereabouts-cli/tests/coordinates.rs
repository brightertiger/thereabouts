//! Coordinate input uses the shared Rust wire contract in both command hosts.
#![allow(clippy::unwrap_used, clippy::indexing_slicing)]
mod support;
use serde_json::{Value, json};
use std::{io::Cursor, path::Path};
use support::{Host, install};

fn batch(host: &mut Host, input: &str, flags: &[&str]) -> i32 {
    host.input = Cursor::new(input.as_bytes().to_vec());
    let mut args = vec!["reverse", "-"];
    args.extend_from_slice(flags);
    host.run(&args)
}
fn rows(host: &Host) -> Vec<Value> {
    host.out
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}
#[test]
fn syntax_is_rejected_without_opening_data() {
    let temp = tempfile::tempdir().unwrap();
    let mut host = Host::new(temp.path());
    for args in [
        vec!["--frame", "ecef", "--x", "1", "--y", "2"],
        vec!["--x", "1", "--y", "2", "--z", "3"],
        vec!["--lat", "1", "--lon", "2", "--height", "3"],
        vec!["--frame", "enu", "--x", "1", "--y", "2", "--z", "3"],
        vec![
            "--frame", "enu", "--x", "1", "--y", "2", "--z", "3", "--origin", "bad",
        ],
        vec![
            "--frame", "ned", "--x", "1", "--y", "2", "--z", "3", "--origin", "[]",
        ],
        vec!["--point", "{"],
        vec!["--point", "[]"],
        vec!["--point", "{}"],
        vec!["--point", "{\"frame\":\"ecef\"}", "--frame", "ecef"],
        vec!["--point", "{\"frame\":\"ecef\"}", "--hdop", "2"],
        vec!["-", "--point", "{\"frame\":\"ecef\"}"],
        vec!["-", "--frame", "ecef", "--x", "1", "--y", "2", "--z", "3"],
        vec!["--frame", "ecef", "--lat", "1", "--lon", "2"],
        vec![
            "--frame", "geodetic", "--lat", "1", "--lon", "2", "--value", "x",
        ],
        vec!["--frame", "llv"],
        vec!["--frame", "crs:EPSG:3857"],
        vec!["--frame", "unknown"],
        vec!["-", "--frame-col", "frame"],
        vec!["-", "--input-format", "nmea"],
        vec!["-", "--input-format", "gpx"],
        vec!["--lat", "0", "--lon", "0", "--input-format", "csv"],
        vec!["-", "--input-format", "ndjson", "--lat-col", "lat"],
        vec!["-", "--frame", "ecef", "--x-col", "a", "--y-col", "a"],
        vec!["-", "--frame", "utm", "--zone", "31", "--zone-col", "zone"],
    ] {
        let mut command = vec!["reverse"];
        command.extend(args);
        assert_eq!(host.run(&command), 2, "{command:?}: {}", host.err);
        assert!(host.out.is_empty(), "{command:?}");
        assert!(!host.err.contains("not installed"), "{command:?}");
    }
    assert_eq!(host.run(&["reverse", "--frame", "llv"]), 2);
    assert!(
        host.err.contains(
            "Choose frame enu or ned and supply an origin; llv does not define axis order"
        )
    );
    assert_eq!(host.run(&["reverse", "--frame", "crs:EPSG:3857"]), 2);
    assert!(host.err.contains("Thereabouts does not transform arbitrary CRSs; use GeoReconcile crs: support or pyproj, then pass WGS84 geodetic coordinates"));
    for args in [
        vec!["reverse", "--help"],
        vec!["reverse", "--fields"],
        vec!["--fields"],
    ] {
        assert_eq!(host.run(&args), 0, "{}", host.err);
        assert!(host.out.contains(if args.contains(&"--help") {
            "--input-format"
        } else {
            "query.normalized.height"
        }));
    }
}
#[test]
fn scalar_flags_and_point_share_provenance_and_legacy_remains_unchanged() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let fixture_path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/coordinates/vectors.json");
    let fixture: Value = serde_json::from_slice(&std::fs::read(fixture_path).unwrap()).unwrap();
    let case = fixture["cases"]
        .as_array()
        .unwrap()
        .iter()
        .find(|v| v["id"] == "msl_with_separation")
        .unwrap();
    let mut point = case["input"].clone();
    point["frame"] = json!("llh");
    point["uncertainty"] = json!({"accuracy_m":4,"hdop":1.2,"vdop":2});
    let flags = scalar_flags(&point);
    assert_eq!(
        host.run(&flags.iter().map(String::as_str).collect::<Vec<_>>()),
        0,
        "{}",
        host.err
    );
    let result: Value = serde_json::from_str(&host.out).unwrap();
    assert_eq!(result["query"]["declared_frame"], "llh");
    assert_eq!(result["query"]["input_frame"], "geodetic");
    assert_eq!(
        result["query"]["normalized"]["height"].as_f64(),
        case["expected"]["normalized"]["height"].as_f64()
    );
    assert_eq!(result["query"]["uncertainty"]["hdop"], 1.2);
    assert_eq!(result["query"]["uncertainty"]["accuracy_m"], 4.0);
    assert!(result.get("evidence").is_none());
    assert_eq!(
        host.run(&["reverse", "--point", &point.to_string()]),
        0,
        "{}",
        host.err
    );
    assert_eq!(serde_json::from_str::<Value>(&host.out).unwrap(), result);
    let lat = point["lat"].to_string();
    let lon = point["lon"].to_string();
    let legacy_args = ["reverse", "--lat", &lat, "--lon", &lon];
    assert_eq!(host.run(&legacy_args), 0);
    let legacy = host.out.clone();
    assert!(!legacy.contains("query"));
    let mut value: Value = serde_json::from_str(&legacy).unwrap();
    value["query"] = result["query"].clone();
    assert_eq!(value, result);
    assert_eq!(host.run(&legacy_args), 0);
    assert_eq!(host.out, legacy);
}
#[test]
fn scalar_domains_are_results_with_exit_two() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    for (point, code, message) in [
        (
            json!({"frame":"geodetic","lat":91,"lon":0}),
            "out_of_range",
            "Coordinate field lat is outside the supported range",
        ),
        (
            json!({"frame":"enu","e":0,"n":0,"u":0}),
            "missing_origin",
            "Frame enu/ned requires an explicit geodetic or ECEF origin",
        ),
        (
            json!({"frame":"crs:EPSG:3857","x":0,"y":0}),
            "unsupported_frame",
            "Thereabouts does not transform arbitrary CRSs; use GeoReconcile crs: support or pyproj, then pass WGS84 geodetic coordinates",
        ),
        (
            json!({"frame":"h3","cell":"891fb466257ffff"}),
            "unsupported_cell_resolution",
            "H3 reverse queries support resolutions 0 through 8; use an explicit parent cell",
        ),
        (
            json!({"frame":"nmea","value":"$GPGGA,broken"}),
            "invalid_checksum",
            "NMEA checksum is missing or invalid",
        ),
    ] {
        assert_eq!(
            host.run(&["reverse", "--point", &point.to_string()]),
            2,
            "{}",
            host.err
        );
        let answer: Value = serde_json::from_str(&host.out).unwrap();
        assert_eq!(answer["status"], "invalid_input");
        assert_eq!(answer["query"]["error"]["code"], code);
        assert_eq!(answer["hint"], message);
        assert_eq!(answer["query"]["error"]["message"], message);
        assert!(answer["query"]["normalized"].is_null());
    }
}
#[test]
fn csv_frames_keep_raw_header_order_and_continue_after_each_failure() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let input = "id,X,Z,Y,note\nfirst,bad,0,0,wrong\ngood,6378137,0,0,\"comma, quote \"\"x\"\"\"\nlast,6378137,0,0,\"two\nlines\"\nshort,1\n";
    let flags = [
        "--frame", "ecef", "--x-col", "X", "--y-col", "Y", "--z-col", "Z", "--csv",
    ];
    assert_eq!(batch(&mut host, input, &flags), 5, "{}", host.err);
    let mut csv = csv::Reader::from_reader(host.out.as_bytes());
    let headers = csv.headers().unwrap().clone();
    assert_eq!(
        headers.iter().take(5).collect::<Vec<_>>(),
        ["id", "X", "Z", "Y", "note"]
    );
    assert_eq!(headers.iter().next_back(), Some("thereabouts_query"));
    let query = headers
        .iter()
        .position(|v| v == "thereabouts_query")
        .unwrap();
    let status = headers
        .iter()
        .position(|v| v == "thereabouts_status")
        .unwrap();
    let records = csv.records().collect::<Result<Vec<_>, _>>().unwrap();
    assert_eq!(records.len(), 4);
    assert_eq!(&records[0][status], "invalid_input");
    assert_eq!(&records[3][status], "invalid_input");
    assert_eq!(&records[1][4], "comma, quote \"x\"");
    assert_eq!(&records[2][4], "two\nlines");
    assert_eq!(
        serde_json::from_str::<Value>(&records[1][query]).unwrap()["input_frame"],
        "ecef"
    );
    for (input, flags) in [
        ("x,y\n1,2\n", vec!["--frame", "ecef"]),
        ("x,y,z,x\n1,2,3,4\n", vec!["--frame", "ecef"]),
        ("x,,z\n1,2,3\n", vec!["--frame", "ecef"]),
        ("x,y,z,thereabouts_id\n1,2,3,4\n", vec!["--frame", "ecef"]),
        ("lat,latitude,lon\n1,2,3\n", vec!["--frame", "geodetic"]),
        (
            "lat,lon\n1,2\n",
            vec!["--frame", "geodetic", "--height-col", "H"],
        ),
        (
            "zone,easting,northing,hemisphere\n31,500000,0,N\n",
            vec!["--frame", "utm", "--zone", "31"],
        ),
        ("coordinates\n[]\n", vec!["--frame", "geojson"]),
    ] {
        assert_eq!(batch(&mut host, input, &flags), 2, "{}", host.err);
    }
}
#[test]
fn csv_local_axes_and_optional_metadata_are_explicit() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let origin = r#"{"frame":"geodetic","lat":48.8566,"lon":2.3522}"#;
    for (frame, input) in [("enu", "e,n,u\n10,20,30\n"), ("ned", "n,e,d\n20,10,-30\n")] {
        assert_eq!(
            batch(&mut host, input, &["--frame", frame, "--origin", origin]),
            0,
            "{}",
            host.err
        );
        let batch = rows(&host);
        let values = if frame == "enu" {
            ["10", "20", "30"]
        } else {
            ["20", "10", "-30"]
        };
        assert_eq!(
            host.run(&[
                "reverse", "--frame", frame, "--x", values[0], "--y", values[1], "--z", values[2],
                "--origin", origin
            ]),
            0,
            "{}",
            host.err
        );
        let scalar: Value = serde_json::from_str(&host.out).unwrap();
        assert_eq!(batch[0]["thereabouts_query"], scalar["query"]);
    }
    let input = "lat,lon,height,height_datum,accuracy_m,hdop,vdop\n48.8566,2.3522,10,unknown,5,0.8,1.1\n48.8566,2.3522,,,,,\n";
    assert_eq!(
        batch(&mut host, input, &["--frame", "latlon"]),
        0,
        "{}",
        host.err
    );
    let output = rows(&host);
    assert_eq!(
        output[0]["thereabouts_query"]["source_height"]["datum"],
        "unknown"
    );
    assert!(output[0]["thereabouts_query"]["normalized"]["height"].is_null());
    assert_eq!(
        output[0]["thereabouts_query"]["uncertainty"]["accuracy_m"],
        5.0
    );
    assert!(output[1]["thereabouts_query"]["uncertainty"]["hdop"].is_null());
    assert_eq!(batch(&mut host, input, &[]), 0);
    assert!(!host.out.contains("thereabouts_query"));
    assert_eq!(
        batch(
            &mut host,
            "value\nPOINT (2.3522 48.8566)\n",
            &["--frame", "wkt"]
        ),
        0,
        "{}",
        host.err
    );
    assert_eq!(batch(&mut host, "value\nPOINT (2.3522 48.8566)\n", &[]), 2);
    assert_eq!(
        batch(
            &mut host,
            "value\n\"48 51 24.1 N,\n2 21 7.9 E\"\n",
            &["--frame", "dms"]
        ),
        0,
        "{}",
        host.err
    );
}
#[test]
fn mixed_ndjson_reserves_query_after_bad_first_row_only_when_needed() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let input = "bad first row\n{\"lat\":48.8566,\"lon\":2.3522}\n{\"frame\":\"ecef\",\"x\":6378137,\"y\":0,\"z\":0,\"tag\":\"東京\"}\n{\"frame\":\"geodetic\",\"lat\":\"0\",\"lon\":0}\n";
    assert_eq!(
        batch(&mut host, input, &["--input-format", "ndjson", "--csv"]),
        5,
        "{}",
        host.err
    );
    let mut csv = csv::Reader::from_reader(host.out.as_bytes());
    let headers = csv.headers().unwrap().clone();
    assert_eq!(headers.iter().next_back(), Some("thereabouts_query"));
    let query = headers
        .iter()
        .position(|v| v == "thereabouts_query")
        .unwrap();
    let records = csv.records().collect::<Result<Vec<_>, _>>().unwrap();
    assert!(records[0][query].is_empty() && records[1][query].is_empty());
    assert_ne!(&records[2][query], "");
    assert_eq!(batch(&mut host, input, &["--input-format", "ndjson"]), 5);
    let output = rows(&host);
    assert!(output[0].get("thereabouts_query").is_none());
    assert!(output[1].get("thereabouts_query").is_none());
    assert_eq!(output[3]["thereabouts_status"], "invalid_input");
    assert_eq!(
        batch(
            &mut host,
            "{\"lat\":0,\"lon\":0,\"x\":\"unrelated\"}\n",
            &["--csv"]
        ),
        0
    );
    assert!(!host.out.contains("thereabouts_query"));
    assert_eq!(
        batch(&mut host, "", &["--input-format", "ndjson", "--json"]),
        0
    );
    assert_eq!(host.out, "{\"results\": []}\n");
}
#[test]
fn ndjson_context_conflicts_and_extra_components_fail_per_row() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let input = "{\"frame\":\"lla\",\"lat\":48.8566,\"lon\":2.3522,\"tag\":7}\n{\"frame\":\"ecef\",\"x\":6378137,\"y\":0,\"z\":0}\n{\"lat\":0,\"lon\":0,\"x\":1}\n";
    assert_eq!(batch(&mut host, input, &["--frame", "geodetic"]), 5);
    let output = rows(&host);
    assert_eq!(output[0]["thereabouts_status"], "matched");
    for row in &output[1..] {
        assert_eq!(row["thereabouts_status"], "invalid_input");
    }
    let origin = json!({"frame":"geodetic","lat":48.8566,"lon":2.3522});
    let input = [
        json!({"e":0,"n":0,"u":0}),
        json!({"e":0,"n":0,"u":0,"origin":{"frame":"llh","lat":48.8566,"lon":2.3522}}),
        json!({"e":0,"n":0,"u":0,"origin":{"lat":0,"lon":0}}),
    ]
    .iter()
    .map(Value::to_string)
    .collect::<Vec<_>>()
    .join("\n");
    assert_eq!(
        batch(
            &mut host,
            &input,
            &["--frame", "enu", "--origin", &origin.to_string()]
        ),
        5,
        "{}",
        host.err
    );
    let output = rows(&host);
    assert_eq!(output[0]["thereabouts_status"], "matched");
    assert_eq!(output[1]["thereabouts_status"], "matched");
    assert_eq!(
        output[2]["thereabouts_query"]["error"]["code"],
        "conflicting_fields"
    );
    assert_eq!(
        batch(
            &mut host,
            "{\"frame\":\"enu\",\"e\":0,\"n\":0,\"u\":0}\n",
            &[]
        ),
        5
    );
    assert_eq!(
        rows(&host)[0]["thereabouts_query"]["error"]["code"],
        "missing_origin"
    );
}
#[test]
fn nmea_logs_validate_every_sentence_and_preserve_raw_input() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let sentence = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47";
    let void = "$GPRMC,123519,V,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*7D";
    let input = format!("\n{sentence}\n\n{void}\n$GPGGA,bad*00\n");
    assert_eq!(
        batch(
            &mut host,
            &input,
            &["--input-format", "nmea", "--frame", "nmea"]
        ),
        5,
        "{}",
        host.err
    );
    let output = rows(&host);
    assert_eq!(output.len(), 3);
    assert_eq!(output[0]["value"], sentence);
    assert_eq!(output[0]["thereabouts_query"]["uncertainty"]["hdop"], 0.9);
    assert_eq!(output[1]["thereabouts_query"]["error"]["code"], "no_fix");
    assert_eq!(
        output[2]["thereabouts_query"]["error"]["code"],
        "invalid_checksum"
    );
    let quoted = format!("value\n\"{sentence}\"\n");
    assert_eq!(
        batch(&mut host, &quoted, &["--frame", "nmea"]),
        0,
        "{}",
        host.err
    );
}
#[test]
fn point_field_selection_and_csv_order_include_query_last() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let point = r#"{"frame":"geodetic","lat":48.8566,"lon":2.3522,"uncertainty":{"hdop":1.2}}"#;
    assert_eq!(host.run(&["reverse", "--point", point, "--csv"]), 0);
    assert!(host.out.lines().next().unwrap().ends_with(",query"));
    host.tty = true;
    assert_eq!(host.run(&["reverse", "--point", point]), 0);
    assert_eq!(
        host.out
            .lines()
            .next()
            .unwrap()
            .split(" | ")
            .map(str::trim)
            .collect::<Vec<_>>(),
        [
            "status", "country", "state", "city", "timezone", "point", "match"
        ]
    );
    host.env.insert("COLUMNS".into(), "48".into());
    assert_eq!(
        host.run(&[
            "reverse",
            "--point",
            point,
            "--fields",
            "query.input_frame,query.uncertainty.hdop"
        ]),
        0,
        "{}",
        host.err
    );
    assert!(host.out.contains("geodetic"));
    assert!(!host.out.contains("normalized"));
}
#[test]
fn old_wasm_batch_options_deserialize_without_coordinate_fields() {
    let options: thereabouts_cli_core::batch::Options=serde_json::from_value(json!({"filename":"-","lat_col":null,"lon_col":null,"evidence":false,"strict":false,"fields":null,"format":"ndjson"})).unwrap();
    assert!(options.coordinates.frame.is_none());
}
fn assert_metadata(actual: &Value, expected: &Value, tolerance: &Value, path: &str, id: &str) {
    match expected {
        Value::Object(object) => {
            for (key, value) in object {
                let next = if path.is_empty() {
                    key.clone()
                } else {
                    format!("{path}.{key}")
                };
                assert_metadata(&actual[key], value, tolerance, &next, id);
            }
        }
        Value::Array(array) => {
            assert_eq!(
                actual.as_array().unwrap().len(),
                array.len(),
                "{id}: {path}"
            );
            for (index, value) in array.iter().enumerate() {
                assert_metadata(&actual[index], value, tolerance, &format!("{path}.*"), id);
            }
        }
        Value::Number(number) => {
            let limit = tolerance[path].as_f64().unwrap_or(0.0);
            let actual = actual.as_f64().unwrap();
            let expected = number.as_f64().unwrap();
            let delta = (actual - expected).abs();
            let delta = if path.rsplit('.').next() == Some("lon") {
                delta.min((360.0 - delta).abs())
            } else {
                delta
            };
            assert!(
                delta <= limit,
                "{id}: {path}: {actual} vs {expected}, tolerance {limit}"
            );
        }
        _ => assert_eq!(actual, expected, "{id}: {path}"),
    }
}
fn scalar_flags(point: &Value) -> Vec<String> {
    let frame = point["frame"].as_str().unwrap();
    let mut flags = vec!["reverse".into(), "--frame".into(), frame.into()];
    for (key, value) in point.as_object().unwrap() {
        if key == "frame" {
            continue;
        }
        if key == "uncertainty" {
            for (name, number) in value.as_object().unwrap() {
                flags.extend([format!("--{}", name.replace('_', "-")), number.to_string()]);
            }
            continue;
        }
        let flag = match (frame, key.as_str()) {
            ("enu", "e") | ("ned", "n") => "x",
            ("enu", "n") | ("ned", "e") => "y",
            ("enu", "u") | ("ned", "d") => "z",
            (_, "cell") => "value",
            _ => key,
        };
        flags.push(format!("--{}", flag.replace('_', "-")));
        flags.push(
            value
                .as_str()
                .map_or_else(|| value.to_string(), str::to_owned),
        );
    }
    flags
}
fn assert_schema(actual: &Value, expected: &Value, id: &str) {
    match expected {
        Value::Object(fields) => {
            let actual = actual.as_object().unwrap();
            assert_eq!(
                actual.keys().collect::<Vec<_>>(),
                fields.keys().collect::<Vec<_>>(),
                "{id}"
            );
            for (key, value) in fields {
                assert_schema(&actual[key], value, id);
            }
        }
        Value::Array(values) => {
            let actual = actual.as_array().unwrap();
            assert_eq!(actual.len(), values.len(), "{id}");
            for (left, right) in actual.iter().zip(values) {
                assert_schema(left, right, id);
            }
        }
        Value::Number(_) => assert!(actual.is_number(), "{id}"),
        _ => assert_eq!(actual, expected, "{id}"),
    }
}
#[test]
fn shared_coordinate_fixtures_drive_scalar_point_and_component_inputs() {
    // Core owns sources and tolerances. Missing vectors fail this gate.
    let path =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/coordinates/vectors.json");
    let fixture: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    assert_eq!(fixture["schema_version"], 1);
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let pack = thereabouts_core::format::Pack::open(
        &Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/core-sample"),
        true,
    )
    .unwrap();
    for case in fixture["cases"].as_array().unwrap() {
        let id = case["id"].as_str().unwrap();
        let mut point = case["input"].clone();
        point
            .as_object_mut()
            .unwrap()
            .entry("frame")
            .or_insert(json!("geodetic"));
        let invalid = case["expected"]["error"].is_string();
        let expected_exit = if invalid { 2 } else { 0 };
        assert_eq!(
            host.run(&["reverse", "--point", &point.to_string()]),
            expected_exit,
            "{id}: {}",
            host.err
        );
        let answer: Value = serde_json::from_str(&host.out).unwrap();
        // Decode both wire results with the same JSON reader. Its decimal-to-f64
        // rounding differs from an in-memory Value on some footprint vertices;
        // Python/Node additionally compare the emitted numbers with their readers.
        let direct: Value = serde_json::from_str(
            &serde_json::to_string(
                &thereabouts_core::coords::reverse_value(&pack, &point, false).unwrap(),
            )
            .unwrap(),
        )
        .unwrap();
        assert_eq!(answer["status"], direct["status"], "{id}");
        assert_schema(&answer["query"], &direct["query"], id);
        assert_metadata(
            &answer["query"],
            &direct["query"],
            &case["tolerance"],
            "",
            id,
        );
        if invalid {
            assert_eq!(answer["status"], "invalid_input", "{id}");
            assert_eq!(
                answer["query"]["error"]["code"], case["expected"]["error"],
                "{id}"
            );
        } else {
            assert_metadata(
                &answer["query"],
                &case["expected"],
                &case["tolerance"],
                "",
                id,
            );
            if point["frame"] != "geojson" {
                let flags = scalar_flags(&point);
                let flags = flags.iter().map(String::as_str).collect::<Vec<_>>();
                assert_eq!(host.run(&flags), 0, "{id}: {}", host.err);
                let scalar: Value = serde_json::from_str(&host.out).unwrap();
                assert_eq!(scalar["status"], direct["status"], "{id}");
                assert_schema(&scalar["query"], &direct["query"], id);
                assert_metadata(
                    &scalar["query"],
                    &direct["query"],
                    &case["tolerance"],
                    "",
                    id,
                );
                assert_metadata(
                    &scalar["query"],
                    &case["expected"],
                    &case["tolerance"],
                    "",
                    id,
                );
            }
        }
    }
}

#[test]
fn uniform_uncertainty_fills_only_missing_row_members() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    let input = r#"{"lat":48.8566,"lon":2.3522,"uncertainty":{"accuracy_m":1.0,"hdop":2}}
{"lat":48.8566,"lon":2.3522,"uncertainty":{"accuracy_m":2}}
{"lat":48.8566,"lon":2.3522,"accuracy_m":1}
"#;
    assert_eq!(
        batch(
            &mut host,
            input,
            &["--frame", "geodetic", "--accuracy-m", "1"]
        ),
        5,
        "{}",
        host.err
    );
    let output = rows(&host);
    assert_eq!(output[0]["thereabouts_status"], "matched");
    assert_eq!(output[0]["thereabouts_query"]["uncertainty"]["hdop"], 2.0);
    assert_eq!(
        output[1]["thereabouts_query"]["error"]["code"],
        "conflicting_fields"
    );
    assert_eq!(
        output[2]["thereabouts_query"]["error"]["code"],
        "conflicting_fields"
    );
}

#[test]
fn nonfinite_cli_numbers_keep_core_diagnostics_without_json_null_coercion() {
    let temp = tempfile::tempdir().unwrap();
    let mut host = Host::new(temp.path());
    assert_eq!(
        host.run(&[
            "reverse", "--frame", "ecef", "--x", "NaN", "--y", "0", "--z", "0"
        ]),
        2
    );
    let value: Value = serde_json::from_str(&host.out).unwrap();
    assert_eq!(value["query"]["error"]["code"], "non_finite");
    assert_eq!(value["hint"], "Coordinate field x must be finite");
    install(temp.path(), &["core"]);
    assert_eq!(
        batch(&mut host, "x,y,z\ninf,0,0\n", &["--frame", "ecef"]),
        5
    );
    assert_eq!(
        rows(&host)[0]["thereabouts_query"]["error"]["code"],
        "non_finite"
    );
}

#[test]
fn h3_frames_preserve_legacy_resolution_and_negative_text_is_a_value() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    for cell in ["801ffffffffffff", "881fb46625fffff"] {
        assert_eq!(host.run(&["h3", cell]), 0, "{}", host.err);
        let legacy: Value = serde_json::from_str(&host.out).unwrap();
        assert_eq!(
            host.run(&["reverse", "--frame", "h3", "--value", cell]),
            0,
            "{}",
            host.err
        );
        let mut point: Value = serde_json::from_str(&host.out).unwrap();
        assert_eq!(point["query"]["conversion"], json!(["h3_stored_ancestor"]));
        point.as_object_mut().unwrap().remove("query");
        assert_eq!(point, legacy);
    }
    assert_eq!(
        host.run(&["reverse", "--frame", "dms", "--value", "-48°N 2°E"]),
        2
    );
    assert_eq!(
        serde_json::from_str::<Value>(&host.out).unwrap()["query"]["error"]["code"],
        "conflicting_fields"
    );
    assert_eq!(host.run(&["reverse", "--frame", "geojson"]), 2);
    assert!(host.err.contains("Use --point JSON or NDJSON"));
}

#[test]
fn raw_csv_frame_column_never_declares_a_row_frame() {
    let temp = tempfile::tempdir().unwrap();
    install(temp.path(), &["core"]);
    let mut host = Host::new(temp.path());
    assert_eq!(
        batch(
            &mut host,
            "frame,x,y,z\ngeodetic,NaN,0,0\n",
            &["--frame", "ecef"]
        ),
        5
    );
    let output = rows(&host);
    assert_eq!(output[0]["frame"], "geodetic");
    assert_eq!(output[0]["thereabouts_query"]["declared_frame"], "ecef");
    assert_eq!(output[0]["thereabouts_query"]["input_frame"], "ecef");
}
