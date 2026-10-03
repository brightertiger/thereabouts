//! Zone overlap is evidence, never reverse ambiguity.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
use serde_json::json;
use std::{collections::BTreeMap, fs, path::PathBuf};
use thereabouts_core::format::{
    Pack, address,
    catalogue::{Place, encode_places},
    container::encode,
    manifest::{self, Artifact},
    metadata::Metadata,
    spatial::{Label, encode_blocks},
};

#[test]
fn overlap_narrows_by_country_and_never_changes_geographic_status() {
    let fixture =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/core-synthetic");
    let cell = h3o::LatLng::new(12.97, 77.59)
        .unwrap()
        .to_cell(h3o::Resolution::Three);
    for (assigned, countries, expected_timezone, expected_zones) in [
        (false, ["AA", "BB"], None, vec!["Area/One", "Area/Two"]),
        (true, ["AA", "BB"], Some("Area/One"), vec![]),
        (true, ["AA", "AA"], None, vec!["Area/One", "Area/Two"]),
        (true, ["BB", "BB"], None, vec!["Area/One", "Area/Two"]),
    ] {
        let dir = tempfile::tempdir().unwrap();
        let mut manifest = manifest::read(&fixture).unwrap();
        manifest.files.clear();
        // This test replaces the inventory with only spatial/catalogue metadata.
        manifest.name_normalization = None;
        let metadata = Metadata {
            timezone_sets: vec![vec![], vec!["Area/One".into(), "Area/Two".into()]],
            zone_tables: vec![
                json!({"tzid":"Area/One","country_codes":countries[0]}),
                json!({"tzid":"Area/Two","country_codes":countries[1]}),
            ],
            ..Metadata::default()
        };
        let mut text: [Option<String>; 12] = std::array::from_fn(|_| Some("test".into()));
        text[0] = Some("country:AA".into());
        text[6] = Some("AA".into());
        text[11] = Some("{}".into());
        let place = Place {
            text,
            refs: [0; 4],
            latitude: i32::MIN,
            longitude: i32::MIN,
            population: 0,
            timezone: None,
        };
        let label = if assigned {
            Label([1, 0, 0, 8, 1])
        } else {
            Label([0, 0, 0, 0, 1])
        };
        for (name, kind, bytes) in [
            (
                "cells.bin",
                "cells",
                encode_blocks(&BTreeMap::from([(
                    address::address(cell).0,
                    vec![(0, label)],
                )]))
                .unwrap(),
            ),
            (
                "catalogue.bin",
                "catalogue",
                encode_places(&[place]).unwrap(),
            ),
            (
                "metadata.bin",
                "metadata",
                encode(3, &[(&serde_json::to_vec(&metadata).unwrap(), 1)]).unwrap(),
            ),
        ] {
            let path = dir.path().join(name);
            fs::write(&path, &bytes).unwrap();
            manifest.files.push(Artifact {
                path: name.into(),
                kind: kind.into(),
                size: bytes.len() as u64,
                sha256: manifest::digest(&path).unwrap(),
            });
        }
        fs::write(
            dir.path().join("manifest.json"),
            serde_json::to_vec(&manifest).unwrap(),
        )
        .unwrap();
        let pack = Pack::open(dir.path(), true).unwrap();
        let result = pack.from_h3(&cell.to_string(), true).unwrap();
        assert_eq!(
            result.status.as_str(),
            if assigned { "matched" } else { "not_found" }
        );
        assert_eq!(result.timezone.as_deref(), expected_timezone);
        assert_eq!(result.candidates, []);
        assert_eq!(result.evidence.unwrap().timezones, expected_zones);
    }
}
