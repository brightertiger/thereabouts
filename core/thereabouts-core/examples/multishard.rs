//! Deterministic cache-miss workload, generated locally rather than committed as binaries.
use h3o::{LatLng, Resolution};
use serde_json::json;
use std::{collections::BTreeMap, fs, path::Path};
use thereabouts_core::{
    Error, Result,
    format::{
        address,
        catalogue::{Place, encode_places},
        container::encode,
        manifest::{self, Artifact, Manifest},
        metadata::Metadata,
        spatial::{Label, encode_blocks},
    },
};
const SHARDS: usize = 256;
const PLACES_PER_SHARD: usize = 64;
fn add(root: &Path, manifest: &mut Manifest, name: &str, kind: &str, bytes: &[u8]) -> Result<()> {
    let path = root.join(name);
    fs::write(&path, bytes)?;
    manifest.files.push(Artifact {
        path: name.into(),
        kind: kind.into(),
        size: bytes.len() as u64,
        sha256: manifest::digest(&path)?,
    });
    Ok(())
}
fn main() -> Result<()> {
    let output = std::env::args()
        .nth(1)
        .ok_or_else(|| Error::Input("Supply output directory".into()))?;
    let single = std::env::args().nth(2).as_deref() == Some("single");
    let count = if single {
        25_000
    } else {
        SHARDS * PLACES_PER_SHARD
    };
    let per_shard = if single { count } else { PLACES_PER_SHARD };
    let output = Path::new(&output);
    fs::create_dir_all(output)?;
    let mut manifest = manifest::read(
        &Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/core-synthetic"),
    )?;
    manifest.files.clear();
    manifest.name_normalization = None;
    manifest.inputs = json!({"benchmark":"catalogue misses", "places":count, "places_per_shard":per_shard, "evidence_padding":2048});
    let root = LatLng::new(52.0, 4.0)
        .map_err(|e| Error::Input(e.to_string()))?
        .to_cell(if single {
            Resolution::Two
        } else {
            Resolution::Three
        });
    let cells: Vec<_> = root.children(Resolution::Eight).take(count).collect();
    let mut rows = BTreeMap::<u32, Vec<(u16, Label)>>::new();
    let mut points = Vec::new();
    for (shard, group) in cells.chunks(per_shard).enumerate() {
        let mut places = Vec::new();
        for (local, cell) in group.iter().enumerate() {
            let i = shard * per_shard + local;
            let reference = u32::try_from(i + 1).map_err(|e| Error::Input(e.to_string()))?;
            let mut text: [Option<String>; 12] = std::array::from_fn(|_| None);
            for (slot, value) in [
                (0, format!("place:{i:05}")),
                (1, format!("Town {i}")),
                (4, "city".into()),
                (5, "town".into()),
                (6, "AA".into()),
                (
                    11,
                    json!({"source_ids":{"id":i,"padding":"x".repeat(2048)}}).to_string(),
                ),
            ] {
                if let Some(field) = text.get_mut(slot) {
                    *field = Some(value);
                }
            }
            places.push(Place {
                text,
                refs: [1, 0, 0, 0],
                latitude: 52_000_000,
                longitude: 4_000_000,
                population: 1000,
                timezone: None,
            });
            let (block, key) = address::address(*cell);
            rows.entry(block)
                .or_default()
                .push((key, Label([1, 0, reference, 9, 0])));
            let centre = LatLng::from(*cell);
            points.push([centre.lat(), centre.lng()]);
        }
        add(
            output,
            &mut manifest,
            &format!("catalogue-{shard:05}.bin"),
            "catalogue",
            &encode_places(&places)?,
        )?;
    }
    add(
        output,
        &mut manifest,
        "cells.bin",
        "cells",
        &encode_blocks(&rows)?,
    )?;
    let metadata = Metadata {
        timezone_sets: vec![vec![]],
        ..Metadata::default()
    };
    add(
        output,
        &mut manifest,
        "metadata.bin",
        "metadata",
        &encode(3, &[(&serde_json::to_vec(&metadata)?, 1)])?,
    )?;
    fs::write(output.join("manifest.json"), serde_json::to_vec(&manifest)?)?;
    thereabouts_core::format::verify::verify(output)?;
    println!("{}", serde_json::to_string(&points)?);
    Ok(())
}
