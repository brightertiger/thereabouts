//! Synthetic search-scale fixtures, not estimates of real-data compressibility.
#[path = "scale/blocks.rs"]
mod blocks;
use serde_json::json;
use std::{fs, path::Path};
use thereabouts_core::{
    Error, Result,
    format::{
        catalogue::{Place, encode_places},
        columns,
        container::{Container, encode, uint},
        manifest::{self, Artifact, Manifest},
        names::{Entry, encode_entries},
    },
};
const INTERVALS: usize = 7_800_000;
const NAMES: usize = 90_000;
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
fn template(family: &str, output: &Path, skip: &[&str]) -> Result<Manifest> {
    fs::create_dir(output)?;
    let root = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join(format!("../../tests/fixtures/packs/{family}-sample"));
    let mut manifest = manifest::read(&root)?;
    manifest.files.retain(|f| !skip.contains(&f.kind.as_str()));
    for f in &manifest.files {
        fs::copy(root.join(&f.path), output.join(&f.path))?;
    }
    manifest.storage = None;
    manifest.inputs =
        json!({"benchmark":"synthetic scale", "intervals": INTERVALS, "names": NAMES});
    Ok(manifest)
}
fn seed_row(role: &str) -> Result<Vec<u64>> {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/packs/ip-sample");
    let file = Container::decode(
        fs::read(root.join(format!("{role}-00000.bin")))?,
        9,
        &[48, 1],
    )?;
    let directory = file.section(0);
    let raw = usize::try_from(uint(directory, 12, 4)?).map_err(|e| Error::Input(e.to_string()))?;
    let packed =
        usize::try_from(uint(directory, 24, 4)?).map_err(|e| Error::Input(e.to_string()))?;
    let payload = file
        .section(1)
        .get(..packed)
        .ok_or_else(|| Error::Input("Missing block".into()))?;
    columns::decode(&columns::decompress(payload, raw)?)?
        .into_iter()
        .next()
        .ok_or_else(|| Error::Input("Empty seed".into()))
}
fn ip(output: &Path) -> Result<()> {
    let mut m = template(
        "ip",
        output,
        &["starts4", "starts6", "evidence4", "evidence6"],
    )?;
    let schema = m
        .forward_columns
        .as_mut()
        .ok_or_else(|| Error::Input("Missing IP schema".into()))?;
    schema.source_rows = INTERVALS as u64;
    let seed = seed_row("starts4")?;
    let location = *seed
        .get(2)
        .ok_or_else(|| Error::Input("Missing location".into()))?;
    let evidence = seed_row("evidence4")?;
    for version in [4, 6] {
        let mut starts = blocks::Output::new(output, &format!("starts{version}"), 9);
        let mut cold = blocks::Output::new(output, &format!("evidence{version}"), 9);
        // Half v4, half v6, with one unassigned address after each interval.
        for first in (0..INTERVALS).step_by(columns::BLOCK_ROWS) {
            let mut rows = Vec::new();
            let mut sources = Vec::new();
            for ordinal in first..(first + columns::BLOCK_ROWS).min(INTERVALS) {
                let address = if version == 4 {
                    ordinal as u128
                } else {
                    (0x2001_u128 << 112) + ordinal as u128
                };
                let low = u64::try_from(address & u128::from(u64::MAX))
                    .map_err(|e| Error::Input(e.to_string()))?;
                let high = u64::try_from(address >> 64).map_err(|e| Error::Input(e.to_string()))?;
                let assigned = ordinal % 2 == 0;
                rows.push((
                    address,
                    vec![high, low, if assigned { location } else { 0 }],
                ));
                sources.push((
                    address,
                    if assigned {
                        evidence.clone()
                    } else {
                        vec![0; 6]
                    },
                ));
            }
            starts.integers(&mut m, &rows)?;
            cold.integers(&mut m, &sources)?;
        }
        starts.finish(&mut m)?;
        cold.finish(&mut m)?;
    }
    fs::write(output.join("manifest.json"), serde_json::to_vec(&m)?)?;
    Ok(())
}
fn name(mut id: usize) -> String {
    let mut suffix = String::new();
    for _ in 0..4 {
        suffix.push(char::from(b'a' + u8::try_from(id % 26).unwrap_or(0)));
        id /= 26;
    }
    format!("Synthetic {suffix} town")
}
fn names(output: &Path) -> Result<()> {
    let mut m = template("core-names", output, &["names", "catalogue", "metadata"])?;
    let place = |id: String, name: String, role: &str| {
        let mut text: [Option<String>; 12] = std::array::from_fn(|_| None);
        for (i, value) in [
            (0, id),
            (1, name),
            (4, role.into()),
            (5, role.into()),
            (6, "AA".into()),
            (7, "AA".into()),
            (11, "{}".into()),
        ] {
            if let Some(field) = text.get_mut(i) {
                *field = Some(value);
            }
        }
        Place {
            text,
            refs: [1, 0, 0, 0],
            latitude: 10_000_000,
            longitude: 20_000_000,
            population: 1000,
            timezone: None,
        }
    };
    add(
        output,
        &mut m,
        "country.bin",
        "catalogue",
        &encode_places(&[place(
            "country:AA".into(),
            "Synthetic country".into(),
            "country",
        )])?,
    )?;
    let mut entries = Vec::new();
    for first in (0..NAMES).step_by(4096) {
        let mut places = Vec::new();
        for i in first..(first + 4096).min(NAMES) {
            let name = name(i);
            places.push(place(format!("city:{i}"), name.clone(), "city"));
            let id = u32::try_from(i + 2).map_err(|e| Error::Input(e.to_string()))?;
            entries.push((
                name.to_ascii_lowercase(),
                Entry {
                    places: [1, 0, id],
                    name,
                    alternate: false,
                },
            ));
        }
        add(
            output,
            &mut m,
            &format!("catalogue-{first}.bin"),
            "catalogue",
            &encode_places(&places)?,
        )?;
    }
    entries.sort_by(|a, b| a.0.cmp(&b.0));
    for (i, part) in entries.chunks(30_000).enumerate() {
        add(
            output,
            &mut m,
            &format!("names-{i}.bin"),
            "names",
            &encode_entries(part)?,
        )?;
    }
    let metadata = json!({"countries":[{"country_code":"AA","alpha3":"AAA","name":"Synthetic country"}],"subdivisions":[],"timezone_sets":[[]],"zone_tables":[]});
    add(
        output,
        &mut m,
        "metadata.bin",
        "metadata",
        &encode(3, &[(&serde_json::to_vec(&metadata)?, 1)])?,
    )?;
    fs::write(output.join("manifest.json"), serde_json::to_vec(&m)?)?;
    Ok(())
}
fn main() -> Result<()> {
    let path = std::env::args()
        .nth(1)
        .ok_or_else(|| Error::Input("Supply output parent".into()))?;
    let root = Path::new(&path);
    fs::create_dir_all(root)?;
    if !root.join("ip").exists() {
        ip(&root.join("ip"))?;
    }
    if !root.join("names").exists() {
        names(&root.join("names"))?;
    }
    Ok(())
}
