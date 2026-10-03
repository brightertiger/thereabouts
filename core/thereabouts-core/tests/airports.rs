//! Original airport expectations remain the oracle; only the default scheme rule changes.
#![allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)]
use std::{fs, path::PathBuf};
use thereabouts_core::format::Pack;
#[test]
fn airport_vectors() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    for name in ["airports-vectors.json", "airports-synthetic-vectors.json"] {
        let bundle: serde_json::Value =
            serde_json::from_slice(&fs::read(root.join(name)).unwrap()).unwrap();
        let pack = Pack::open(&root.join(bundle["pack"].as_str().unwrap()), true).unwrap();
        for case in bundle["cases"].as_array().unwrap() {
            let r = &case["request"];
            let answer = pack
                .airport(
                    r["values"][0].as_str().unwrap_or(""),
                    r["scheme"].as_str(),
                    r["country"].as_str(),
                    false,
                )
                .unwrap();
            assert_eq!(
                serde_json::to_value(answer).unwrap(),
                case["result"],
                "{}",
                case["id"]
            );
        }
    }
}
#[test]
fn original_airport_expectations() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures");
    let pack = Pack::open(&root.join("packs/airports-synthetic"), true).unwrap();
    let bundle: serde_json::Value =
        serde_json::from_slice(&fs::read(root.join("conformance.json")).unwrap()).unwrap();
    let cases = bundle["cases"].as_array().unwrap();
    let mut counts = [0; 4];
    for case in cases.iter().filter(|c| c["request"]["kind"] == "airport") {
        let r = &case["request"];
        let answer = pack
            .airport(
                r["values"][0].as_str().unwrap_or(""),
                r["scheme"].as_str(),
                r["country"].as_str(),
                true,
            )
            .unwrap();
        // Case 52 used to require a scheme. Its default lookup now has exactly
        // the same airports as the original IATA query in case 32.
        let previous = if case["id"] == 52 {
            cases.iter().find(|c| c["id"] == 32).unwrap()
        } else {
            case
        };
        if previous.get("error").is_some() {
            assert_eq!(answer.status.as_str(), "invalid_input");
            assert!(answer.hint.is_some());
            counts[3] += 1;
            continue;
        }
        let old = &previous["result"];
        assert_eq!(answer.status.as_str(), old["status"].as_str().unwrap());
        let answers = match answer.status.as_str() {
            "matched" => {
                counts[0] += 1;
                vec![answer]
            }
            "ambiguous" => {
                counts[1] += 1;
                // Approved flat consensus; candidate legacy geography remains checked below.
                let mut consensus = answer.candidates.first().and_then(|c| c.country.clone());
                for candidate in &answer.candidates {
                    if candidate.country != consensus {
                        consensus = None;
                        break;
                    }
                }
                assert_eq!(answer.country, consensus);
                answer.candidates
            }
            "not_found" => {
                counts[2] += 1;
                continue;
            }
            other => panic!("Unexpected status {other}"),
        };
        assert_eq!(answers.len(), old["candidates"].as_array().unwrap().len());
        for answer in answers {
            assert_eq!(answer.r#match.unwrap().as_str(), "exact");
            let e = answer.evidence.unwrap();
            let sources = e.source_ids.unwrap();
            let identity = format!(
                "airport:{}:{}",
                sources[0]["source"].as_str().unwrap(),
                sources[0]["source_id"].as_str().unwrap()
            );
            let prior = old["candidates"]
                .as_array()
                .unwrap()
                .iter()
                .find(|c| c["id"] == identity)
                .unwrap();
            assert_eq!(e.country_id.as_deref(), prior["country"]["id"].as_str());
            assert_eq!(e.state_id.as_deref(), prior["state"]["id"].as_str());
            assert_eq!(e.city_id.as_deref(), prior["city"]["id"].as_str());
            if let Some(city) = answer.city {
                assert_eq!(city.name, "München 東京");
            }
            for observation in prior["observations"].as_array().unwrap() {
                assert!(
                    sources
                        .as_array()
                        .unwrap()
                        .iter()
                        .any(|s| s["source"] == observation["source"]
                            && s["source_id"] == observation["source_id"])
                );
            }
        }
    }
    assert_eq!(counts, [7, 2, 1, 1]);
}
