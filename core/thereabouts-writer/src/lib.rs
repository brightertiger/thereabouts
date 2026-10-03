//! Deterministic, bounded dataset-to-pack export. Sources are opened read-only.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
mod catalogue;
mod emission;
mod error;
mod source;
mod timezones;
use error::ensure;
pub use error::{Error, Result};
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use source::Dataset;
pub use source::MEMORY_BUDGET_BYTES;
use std::{collections::BTreeMap, fs, path::Path};
use thereabouts_core::format;
use thereabouts_core::format::{
    manifest::{Artifact, Manifest, digest},
    metadata::Metadata,
};

/// Explicit release identity and attribution; no release version is guessed.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Options {
    pub data_version: String,
    #[serde(default)]
    pub sources: Value,
    #[serde(default)]
    pub attribution: String,
    #[serde(default)]
    pub notices: BTreeMap<String, String>,
    #[serde(default)]
    pub input_provenance: Value,
}
/// Export a core pack atomically. Repeated identical requests verify and return.
/// A changed dataset or options never overwrites an existing published pack.
pub fn write_pack(
    dataset_dir: &Path,
    family: &str,
    output: &Path,
    options: &Options,
) -> Result<Manifest> {
    if family != "core" {
        return Err(Error::Incompatible(
            "Only the core family is implemented".into(),
        ));
    }
    ensure(
        !options.data_version.is_empty(),
        "Dataset version is required",
    )?;
    let data = Dataset::open(dataset_dir)?;
    let identity = json!({"manifest_sha256":data.digest,"options":options,"writer":"0.1.0"});
    let input_digest = format!("{:x}", Sha256::digest(serde_json::to_vec(&identity)?));
    if output.exists() {
        let manifest = format::verify::verify(output)?;
        ensure(
            manifest.input_digest == input_digest,
            "Existing pack has different inputs",
        )?;
        return Ok(manifest);
    }
    let parent = output
        .parent()
        .ok_or_else(|| Error::Input("Output needs a parent directory".into()))?;
    fs::create_dir_all(parent)?;
    let name = output
        .file_name()
        .and_then(|s| s.to_str())
        .ok_or_else(|| Error::Input("Invalid output name".into()))?;
    let stage = parent.join(format!(".{name}.building"));
    // create_dir is the exclusive writer lock; interrupted work is kept for review.
    fs::create_dir(&stage)?;
    let result = build(&data, &stage, options, input_digest, identity);
    match result {
        Ok(manifest) => {
            fs::rename(&stage, output)?;
            Ok(manifest)
        }
        Err(error) => {
            fs::remove_dir_all(&stage)?;
            Err(error)
        }
    }
}
fn build(
    data: &Dataset,
    stage: &Path,
    options: &Options,
    input_digest: String,
    identity: Value,
) -> Result<Manifest> {
    let db_path = stage.join("catalogue.sqlite");
    let db = Connection::open(&db_path)?;
    catalogue::initialize(&db)?;
    db.execute_batch("BEGIN")?;
    catalogue::load(&db, data)?;
    timezones::load(&db, data)?;
    db.execute_batch("COMMIT")?;
    let mut metadata = Metadata {
        timezone_sets: vec![vec![]],
        ..Metadata::default()
    };
    // Metadata remains a small side table; reject unexpectedly large inputs.
    let mut metadata_bytes = 0;
    for (kind, rows) in [
        ("countries", &mut metadata.countries),
        ("subdivisions", &mut metadata.subdivisions),
        ("zone_tables", &mut metadata.zone_tables),
    ] {
        for table in data.tables(kind) {
            data.scan(table, |row| {
                metadata_bytes += serde_json::to_vec(&row)?.len();
                ensure(
                    metadata_bytes <= 16 * 1024 * 1024,
                    "Metadata exceeds admission budget",
                )?;
                rows.push(row);
                Ok(())
            })?;
        }
    }
    let policy = source::field(source::field(&data.manifest, "normalization"), "policy");
    let mut manifest = Manifest {
        schema: "thereabouts-pack-2".into(),
        format_version: 2,
        family: "core".into(),
        data_version: options.data_version.clone(),
        required_features: 0,
        reference_resolution: 8,
        block_resolution: 3,
        input_digest,
        inputs: identity,
        sources: options.sources.clone(),
        attribution: options.attribution.clone(),
        files: vec![],
        distant_over_m: policy["distant_m"]
            .as_u64()
            .and_then(|v| v.try_into().ok())
            .unwrap_or(25000),
        cutoff_m: policy["nearest_m"]
            .as_u64()
            .and_then(|v| v.try_into().ok())
            .unwrap_or(50000),
    };
    emission::cells(data, &db, stage, &mut manifest, &mut metadata)?;
    emission::catalogue(&db, stage, &mut manifest)?;
    add(
        stage,
        &mut manifest,
        "metadata.bin",
        "metadata",
        &format::container::encode(3, &[(&serde_json::to_vec(&metadata)?, 1)])?,
    )?;
    for (i, (name, text)) in options.notices.iter().enumerate() {
        add(
            stage,
            &mut manifest,
            &format!("notice-{i:03}.txt"),
            "notice",
            format!("{name}\n\n{text}").as_bytes(),
        )?;
    }
    drop(db);
    fs::remove_file(db_path)?;
    let mut json = serde_json::to_vec(&manifest)?;
    json.push(b'\n');
    fs::write(stage.join("manifest.json"), json)?;
    format::verify::verify(stage)?;
    Ok(manifest)
}
fn add(stage: &Path, manifest: &mut Manifest, name: &str, kind: &str, bytes: &[u8]) -> Result<()> {
    let path = stage.join(name);
    fs::write(&path, bytes)?;
    manifest.files.push(Artifact {
        path: name.into(),
        kind: kind.into(),
        size: bytes.len() as u64,
        sha256: digest(&path)?,
    });
    Ok(())
}
fn flags(row: &Value) -> Result<u32> {
    let methods = [
        "",
        "city_polygon",
        "policy_polygon",
        "urban_allocation",
        "town_radius",
        "rural_polygon",
        "rural_nearest",
        "rural_nearest_distant",
    ];
    let method = row["city_method"].as_str().unwrap_or("");
    let city = methods
        .iter()
        .position(|m| *m == method)
        .ok_or_else(|| Error::Input("Unknown city method".into()))?;
    ensure(
        ["country_method", "state_method"]
            .iter()
            .all(|k| row[k].is_null() || row[k] == "area")
            && (row["land_method"] == "land" || row["land_method"] == "offshore"),
        "Unknown assignment method",
    )?;
    Ok(
        u32::try_from(city).map_err(|_| Error::Input("Invalid city method".into()))?
            | if row["country_method"].is_null() {
                0
            } else {
                8
            }
            | if row["state_method"].is_null() { 0 } else { 16 }
            | if row["land_method"] == "offshore" {
                32
            } else {
                0
            },
    )
}
