//! Shared forward snapshots supplement direct legacy and independent source assertions.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
use std::{fs, path::PathBuf};
use thereabouts_core::format::Pack;
#[test]
fn postal_vectors() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    for name in ["postal-vectors.json", "postal-synthetic-vectors.json"] {
        let bundle: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(name)).unwrap()).unwrap();
        let pack = Pack::open(&root.join(bundle["pack"].as_str().unwrap()), true).unwrap();
        for case in bundle["cases"].as_array().unwrap() {
            let request = &case["request"];
            let result = pack
                .postal(
                    request["values"][0].as_str().unwrap_or(""),
                    request["country"].as_str(),
                    false,
                )
                .unwrap();
            assert_eq!(
                serde_json::to_value(result).unwrap(),
                case["result"],
                "{}",
                case["id"]
            );
        }
    }
}
#[test]
fn original_postal_expectations() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    let pack = Pack::open(&root.join("packs/postal-synthetic"), true).unwrap();
    let bundle: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("conformance.json")).unwrap()).unwrap();
    let mut counts = [0; 4];
    for case in bundle["cases"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|c| c["request"]["kind"] == "postal")
    {
        let request = &case["request"];
        let result = pack
            .postal(
                request["values"][0].as_str().unwrap_or(""),
                request["country"].as_str(),
                true,
            )
            .unwrap();
        if case.get("error").is_some() {
            assert_eq!(result.status.as_str(), "invalid_input");
            counts[3] += 1;
            continue;
        }
        assert_eq!(
            result.status.as_str(),
            case["result"]["status"].as_str().unwrap()
        );
        if result.status.as_str() == "not_found" {
            counts[2] += 1;
            continue;
        }
        let answers = if result.status.as_str() == "ambiguous" {
            counts[1] += 1;
            result.candidates
        } else {
            counts[0] += 1;
            vec![result]
        };
        let old = case["result"]["candidates"].as_array().unwrap();
        assert_eq!(answers.len(), old.len());
        for answer in answers {
            assert_eq!(answer.r#match.unwrap().as_str(), "exact");
            let evidence = answer.evidence.unwrap();
            let previous = old
                .iter()
                .find(|c| c["city"]["id"].as_str() == evidence.city_id.as_deref())
                .unwrap();
            assert_eq!(
                previous["country"]["id"].as_str(),
                evidence.country_id.as_deref()
            );
            assert_eq!(
                previous["state"]["id"].as_str(),
                evidence.state_id.as_deref()
            );
            if let Some(country) = answer.country {
                assert_eq!(
                    country.code,
                    previous["country"]["country_code"].as_str().unwrap()
                );
                assert_eq!(country.name, previous["country"]["name"].as_str().unwrap());
            }
            if let Some(state) = answer.state {
                assert_eq!(state.name, previous["state"]["name"].as_str().unwrap());
            }
            if let Some(city) = answer.city {
                assert_eq!(
                    city.name,
                    if city.id == "city:synthetic:A" {
                        "München 東京"
                    } else {
                        previous["city"]["name"].as_str().unwrap()
                    }
                );
            }
        }
    }
    assert_eq!(counts, [4, 1, 1, 2]);
}
