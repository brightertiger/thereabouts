//! Deterministic, bounded dataset-to-pack export. Sources are opened read-only.
#![cfg_attr(
    test,
    allow(clippy::unwrap_used, clippy::expect_used, clippy::indexing_slicing)
)]
mod airport_evidence;
mod airports;
mod arrow;
mod blocks;
mod catalogue;
mod compact;
mod compact_ip;
mod compact_metadata;
mod dictionaries;
mod emission;
mod error;
mod forward;
mod forward_catalogue;
mod geography;
mod inserts;
mod ip;
mod locode;
mod names;
mod packed_staging;
mod phone;
mod plate_columns;
mod plates;
mod postal;
mod source;
mod staging;
mod storage;
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
// Encoding revision is independent of the library release and changes when bytes change.
const WRITER_REVISION: &str = "0.3.1";
use thereabouts_core::format;
use thereabouts_core::format::{
    manifest::{Artifact, Manifest, digest},
    metadata::Metadata,
};

/// Explicit release identity and attribution; no release version is guessed.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Options {
    /// Explicit release label; the writer never guesses a dataset version.
    pub data_version: String,
    /// Parent for both the exclusive stage and SQLite file; omitted from pack identity.
    #[serde(default, skip_serializing)]
    pub staging_directory: Option<std::path::PathBuf>,
    /// Optional SQLite scratch parent, including another filesystem; never part of pack identity.
    #[serde(default, skip_serializing)]
    pub sqlite_directory: Option<std::path::PathBuf>,
    /// Explicit omissions for deliberately incomplete fixtures, never inferred.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub allow_missing_tables: Vec<String>,
    #[serde(default)]
    /// Source descriptions retained verbatim in the pack manifest.
    pub sources: Value,
    #[serde(default)]
    /// Human-readable credit for the included sources.
    pub attribution: String,
    #[serde(default)]
    /// Named license or dataset notices emitted as inventoried artifacts.
    pub notices: BTreeMap<String, String>,
    #[serde(default)]
    /// Original input digests and subset policy when exporting a derived sample.
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
    if !matches!(
        family,
        "core" | "postal" | "airports" | "locode" | "phone" | "ip" | "plates"
    ) {
        return Err(Error::Input("Unsupported export family".into()));
    }
    ensure(
        !options.data_version.is_empty(),
        "Dataset version is required",
    )?;
    let data = Dataset::open(dataset_dir)?;
    if family == "core" {
        data.validate_core(&options.allow_missing_tables)?;
    } else {
        let mut required = vec![
            primary_table(family),
            "places",
            "canonical_cities",
            "place_to_city",
            "countries",
            "subdivisions",
        ];
        if family == "phone" {
            required.push("phone_metadata");
        }
        if family == "plates" {
            required.extend(["plate_codes", "plate_policy", "plate_priors"]);
        }
        data.require_tables(&required, &options.allow_missing_tables)?;
    }
    let revision = if family == "core" {
        "0.2.0" // Core exports now include canonical-city spellings.
    } else if family == "postal" {
        "0.3.2" // Preserve key countries for observations without linked places.
    } else {
        WRITER_REVISION
    };
    let mut identity = json!({"manifest_sha256":data.digest,"options":options,"writer":revision});
    if family != "core"
        && let Some(fields) = identity.as_object_mut()
    {
        fields.insert("family".into(), family.into());
    }
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
    let stage_parent = options.staging_directory.as_deref().unwrap_or(parent);
    staging::preflight(&data, stage_parent, parent, family)?;
    let stage = stage_parent.join(format!(".{name}.building"));
    // create_dir is the exclusive writer lock; interrupted work is kept for review.
    fs::create_dir(&stage).map_err(|error| {
        if error.kind() == std::io::ErrorKind::AlreadyExists {
            Error::Input(format!(
                "Staging directory exists; remove {} and retry",
                stage.display()
            ))
        } else {
            error.into()
        }
    })?;
    let result = build(&data, &stage, options, input_digest, identity, family);
    match result {
        Ok(manifest) => {
            fs::rename(&stage, output)?;
            Ok(manifest)
        }
        Err(error) => {
            // Cleanup is best effort; never hide the original export failure.
            let _ = fs::remove_dir_all(&stage);
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
    family: &str,
) -> Result<Manifest> {
    let sqlite_parent = options.sqlite_directory.as_deref().unwrap_or(stage);
    staging::sqlite_preflight(data, sqlite_parent, family)?;
    let db_file = tempfile::NamedTempFile::new_in(sqlite_parent)?;
    let db = Connection::open(db_file.path())?;
    catalogue::initialize(&db)?;
    db.execute_batch("BEGIN")?;
    catalogue::load(&db, data, primary_table(family))?;
    match family {
        "core" => timezones::load(&db, data)?,
        "postal" => postal::load(data, &db)?,
        "airports" => airports::load(data, &db)?,
        "locode" => locode::load(data, &db)?,
        "phone" => phone::load(data, &db)?,
        "ip" => ip::load(data, &db)?,
        "plates" => {}
        _ => return Err(Error::Input("Unsupported export family".into())),
    }
    let mut metadata = metadata(data, family)?;
    if !matches!(family, "core" | "plates") {
        compact_metadata::trim(&db, &mut metadata, family)?;
    }
    let policy = source::field(source::field(&data.manifest, "normalization"), "policy");
    let mut manifest = Manifest {
        format_minor: 0,
        forward_columns: None,
        plate_columns: None,
        storage: None,
        schema: "thereabouts-pack-2".into(),
        format_version: 2,
        family: family.into(),
        data_version: options.data_version.clone(),
        required_features: 0,
        reference_resolution: 8,
        block_resolution: 3,
        input_digest,
        inputs: identity,
        sources: options.sources.clone(),
        attribution: options.attribution.clone(),
        files: vec![],
        name_normalization: if family == "core" {
            Some(thereabouts_core::name_normalization::Policy::default())
        } else {
            None
        },
        normalization: normalization(family).iter().map(|s| (*s).into()).collect(),
        distant_over_m: if family == "core" {
            source::policy_distance(policy, "distant_m")?
        } else {
            0
        },
        cutoff_m: if family == "core" {
            source::policy_distance(policy, "nearest_m")?
        } else {
            0
        },
    };
    if family == "core" {
        emission::cells(data, &db, stage, &mut manifest, &mut metadata)?;
        names::emit(data, &db, stage, &mut manifest)?;
    } else if family == "plates" {
        plates::emit(
            data,
            &db,
            stage,
            &mut manifest,
            &mut metadata,
            &options.allow_missing_tables,
        )?;
    } else {
        compact::emit(&db, stage, &mut manifest)?;
    }
    emission::catalogue(&db, stage, &mut manifest)?;
    db.execute_batch("COMMIT")?;
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
    db_file.close()?;
    storage::report(stage, &mut manifest)?;
    let mut json = serde_json::to_vec(&manifest)?;
    json.push(b'\n');
    fs::write(stage.join("manifest.json"), json)?;
    format::verify::verify(stage)?;
    Ok(manifest)
}
fn metadata(data: &Dataset, family: &str) -> Result<Metadata> {
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
        if kind == "zone_tables" && family != "core" {
            continue;
        }
        for table in data.tables(kind) {
            data.scan(table, |row| {
                let row = row.metadata()?;
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
    Ok(metadata)
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
fn flags(row: arrow::Row<'_>) -> Result<u32> {
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
    let method = row.text("city_method")?.unwrap_or("");
    let city = methods
        .iter()
        .position(|m| *m == method)
        .ok_or_else(|| Error::Input("Unknown city method".into()))?;
    let country = row.text("country_method")?;
    let state = row.text("state_method")?;
    let land = row.text("land_method")?;
    ensure(
        [country, state]
            .iter()
            .all(|m| m.is_none() || *m == Some("area"))
            && matches!(land, Some("land" | "offshore")),
        "Unknown assignment method",
    )?;
    Ok(
        u32::try_from(city).map_err(|_| Error::Input("Invalid city method".into()))?
            | if country.is_none() { 0 } else { 8 }
            | if state.is_none() { 0 } else { 16 }
            | if land == Some("offshore") { 32 } else { 0 },
    )
}

fn primary_table(family: &str) -> &str {
    match family {
        "core" => "cells",
        "postal" => "postal_codes",
        "locode" => "trade_locations",
        "phone" => "phone_prefixes",
        "ip" => "ip_ranges",
        "plates" => "plate_formats",
        other => other,
    }
}
fn normalization(family: &str) -> &[&str] {
    match family {
        "postal" => &postal::NORMALIZATION,
        "ip" => &["ip_literal"],
        "plates" => &["nfc", "upper_ascii", "collapse_python_whitespace"],
        "phone" => &["e164_plus", "strip_phone_presentation"],
        "airports" | "locode" => &airports::NORMALIZATION,
        _ => &[],
    }
}
