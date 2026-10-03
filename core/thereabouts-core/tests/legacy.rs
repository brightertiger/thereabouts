//! Legacy expectations remain independent of regenerated result snapshots.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
use serde_json::Value;
use std::{fs, path::PathBuf};
use thereabouts_core::{format::Pack, result::LookupResult};

#[test]
fn thirty_five_original_reverse_requests_have_explicit_mappings() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    let legacy: Value =
        serde_json::from_slice(&fs::read(root.join("conformance.json")).unwrap()).unwrap();
    let pack = Pack::open(&root.join("packs/core-synthetic"), true).unwrap();
    let mut counts = [0; 6];
    for case in legacy["cases"].as_array().unwrap() {
        let request = &case["request"];
        let values = &request["values"];
        let actual = match request["kind"].as_str().unwrap() {
            "h3" => pack
                .from_h3(values[0].as_str().unwrap_or(""), true)
                .unwrap(),
            "coordinates" => match (values[0].as_f64(), values[1].as_f64()) {
                (Some(lat), Some(lon)) => pack.reverse(lat, lon, true).unwrap(),
                _ => LookupResult::empty("invalid_input"),
            },
            _ => continue,
        };
        if case["id"] == 47 {
            assert_eq!(values[0], "836014fffffffff");
            assert_eq!(actual.status, "not_found");
            assert_eq!(
                actual.evidence.unwrap().reason.as_deref(),
                Some("no_stored_ancestor")
            );
            counts[5] += 1;
            continue;
        }
        if !case["error"].is_null() {
            assert_eq!(case["error"]["name"], "InvalidInputError");
            assert_eq!(actual.status, "invalid_input");
            counts[4] += 1;
            continue;
        }
        let expected = &case["result"];
        if expected["status"] != "matched" {
            let (bucket, reason) = match expected["status"].as_str().unwrap() {
                "unassigned" => (1, "unassigned"),
                "ineligible" => (2, "no_land"),
                "outside_coverage" => (3, "outside_coverage"),
                status => panic!("unexpected legacy status: {status}"),
            };
            assert_eq!(actual.status, "not_found");
            assert_eq!(actual.evidence.unwrap().reason.as_deref(), Some(reason));
            assert!(actual.country.is_none() && actual.state.is_none() && actual.city.is_none());
            counts[bucket] += 1;
            continue;
        }
        counts[0] += 1;
        let actual = serde_json::to_value(actual).unwrap();
        let old = &expected["selected"];
        assert_eq!(actual["status"], "matched");
        for field in ["country", "state", "city"] {
            assert_eq!(actual["evidence"][format!("{field}_id")], old[field]["id"]);
            if old[field].is_null() {
                assert!(actual[field].is_null());
                continue;
            }
            if field == "country" {
                assert_eq!(actual[field]["code"], old[field]["country_code"]);
            }
            if field == "city" {
                assert_eq!(actual[field]["id"], old[field]["id"]);
            }
            // The sole display-name migration is from place to canonical-city name.
            if field == "city" && old[field]["id"] == "city:synthetic:A" {
                assert_eq!(old[field]["name"], "München 東京 city:synthetic:A");
                assert_eq!(actual[field]["name"], "München 東京");
            } else {
                assert_eq!(actual[field]["name"], old[field]["name"]);
            }
        }
        let method = match old["methods"]["city"].as_str() {
            Some("rural_nearest") => "nearest",
            Some("rural_nearest_distant") => "nearest_distant",
            _ => "contained",
        };
        assert_eq!(actual["match"], method);
        assert_eq!(actual["evidence"]["city_method"], old["methods"]["city"]);
        assert_eq!(actual["evidence"]["land_method"], old["methods"]["land"]);
    }
    assert_eq!(counts, [19, 1, 4, 2, 8, 1]);
}
