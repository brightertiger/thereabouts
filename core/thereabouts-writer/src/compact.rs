//! Compact source records, independent of family-key multiplicity.
use crate::{Error, Result, add, blocks::Output, dictionaries::Dictionaries, error::ensure};
use rusqlite::Connection;
use std::{fs, path::Path};
use thereabouts_core::format::{
    self, columns, compact::Schema, container, manifest::Manifest, observation::Observation, table,
};
pub(crate) struct Rows<'a> {
    output: Output<'a>,
    values: Vec<(u128, Vec<u64>)>,
    pub(crate) count: usize,
}
impl<'a> Rows<'a> {
    pub(crate) fn new(stage: &'a Path, role: &str) -> Self {
        Self {
            output: Output::new(stage, role, table::INTEGER_KIND),
            values: vec![],
            count: 0,
        }
    }
    pub(crate) fn push(&mut self, manifest: &mut Manifest, key: u128, row: Vec<u64>) -> Result<()> {
        self.values.push((key, row));
        self.count += 1;
        if self.values.len() == columns::BLOCK_ROWS {
            self.output.integers(manifest, &self.values)?;
            self.values.clear();
        }
        Ok(())
    }
    pub(crate) fn finish(mut self, manifest: &mut Manifest) -> Result<()> {
        self.output.integers(manifest, &self.values)?;
        self.output.finish(manifest)
    }
}
pub(crate) fn record(row: &rusqlite::Row<'_>) -> rusqlite::Result<(String, Observation)> {
    let mut text = std::array::from_fn(|_| None);
    for (i, value) in text.iter_mut().enumerate() {
        *value = row.get(6 + i)?;
    }
    Ok((
        row.get(0)?,
        Observation {
            identity: None,
            places: [row.get(1)?, row.get(2)?, row.get(3)?],
            latitude: row.get(4)?,
            longitude: row.get(5)?,
            text,
        },
    ))
}
pub(crate) fn encode_record(
    dict: &Dictionaries<'_>,
    record: &Observation,
    family: &str,
) -> Result<(u64, Vec<u64>)> {
    let geo = dict.tuple("geographies", &record.places.map(u64::from))?;
    let name = dict.string(record.text.get(2).and_then(Option::as_deref), true)?;
    let location = dict.tuple(
        "locations",
        &[
            geo,
            u64::from(record.latitude.cast_unsigned()),
            u64::from(record.longitude.cast_unsigned()),
            name,
        ],
    )?;
    let mut detail = 0;
    if let Some(json) = record.text.get(5).and_then(Option::as_deref) {
        let fields = format::compact::detail_fields(family);
        let object = serde_json::from_str::<serde_json::Value>(json)?;
        let object = object
            .as_object()
            .ok_or_else(|| Error::Input("Expected detail object".into()))?;
        ensure(
            object.keys().all(|k| fields.contains(&k.as_str())),
            "Unknown source detail column",
        )?;
        let mut values = Vec::new();
        for field in fields {
            let value = object.get(*field).map(serde_json::to_string).transpose()?;
            values.push(dict.string(value.as_deref(), true)?);
        }
        detail = dict.tuple("details", &values)?;
    }
    let source = record.text.first().and_then(Option::as_deref);
    let identity = record
        .text
        .get(1)
        .and_then(Option::as_deref)
        .ok_or_else(|| Error::Input("Missing source identity".into()))?;
    let (prefix, line) = identity
        .rsplit_once(':')
        .and_then(|(p, n)| {
            n.parse::<u32>()
                .ok()
                .filter(|number| number.to_string() == n)
                .map(|n| (format!("{p}:"), u64::from(n) + 1))
        })
        .unwrap_or_else(|| (identity.into(), 0));
    // Codes are derived from keys or address bounds. Schemes are data only for phone metadata.
    let scheme = if family == "phone" {
        dict.string(record.text.get(4).and_then(Option::as_deref), true)?
    } else {
        0
    };
    Ok((
        location,
        vec![
            dict.string(source, true)?,
            dict.string(Some(&prefix), true)?,
            line,
            0,
            scheme,
            detail,
        ],
    ))
}
pub(crate) fn emit(db: &Connection, stage: &Path, manifest: &mut Manifest) -> Result<()> {
    manifest.format_minor = 1;
    let family = manifest.family.clone();
    let dict = Dictionaries::new(db)?;
    let count = if family == "ip" {
        crate::compact_ip::emit(db, stage, manifest, &dict)?
    } else {
        exact(db, stage, manifest, &dict)?
    };
    dict.emit(
        stage,
        manifest,
        format::compact::detail_fields(&family).len(),
    )?;
    manifest.forward_columns = Some(Schema {
        detail_fields: format::compact::detail_fields(&family)
            .iter()
            .map(|s| (*s).into())
            .collect(),
        source_rows: count as u64,
    });
    Ok(())
}
fn exact(
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
    dict: &Dictionaries<'_>,
) -> Result<usize> {
    let airport = manifest.family == "airports";
    if airport {
        validate_airport_identity(db)?;
        db.execute_batch("CREATE TABLE airport_rows(source TEXT,source_id TEXT,id INTEGER,PRIMARY KEY(source,source_id)) WITHOUT ROWID")?;
    }
    let sql = if airport {
        "SELECT * FROM observations GROUP BY source,source_id ORDER BY source COLLATE BINARY,source_id COLLATE BINARY"
    } else {
        "SELECT * FROM observations ORDER BY key COLLATE BINARY,source COLLATE BINARY,source_id COLLATE BINARY,name COLLATE BINARY"
    };
    let mut query = db.prepare(sql)?;
    let mut records = Rows::new(stage, "records");
    let mut evidence = Rows::new(stage, "evidence");
    let file = stage.join(".keys.fst");
    let mut keys = fst::MapBuilder::new(fs::File::create(&file)?).map_err(fst_error)?;
    let mut previous = None;
    for row in query.query_map([], record)? {
        let (key, record) = row?;
        let ordinal = records.count;
        if airport {
            db.prepare_cached("INSERT INTO airport_rows VALUES(?,?,?)")?
                .execute(rusqlite::params![
                    record.text.first().and_then(Option::as_deref),
                    record.text.get(1).and_then(Option::as_deref),
                    ordinal
                ])?;
        } else if previous.as_ref() != Some(&key) {
            keys.insert(&key, ordinal as u64).map_err(fst_error)?;
            previous = Some(key);
        }
        let (location, fields) = encode_record(dict, &record, &manifest.family)?;
        records.push(manifest, ordinal as u128, vec![location])?;
        evidence.push(manifest, ordinal as u128, fields)?;
    }
    let count = records.count;
    records.finish(manifest)?;
    evidence.finish(manifest)?;
    if airport {
        let mut postings = Rows::new(stage, "postings");
        let mut query=db.prepare("SELECT o.key,a.id FROM observations o JOIN airport_rows a ON o.source=a.source AND o.source_id=a.source_id GROUP BY o.key,a.id ORDER BY o.key COLLATE BINARY,a.id")?;
        for row in query.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, u64>(1)?)))? {
            let (key, id) = row?;
            if previous.as_ref() != Some(&key) {
                keys.insert(&key, postings.count as u64)
                    .map_err(fst_error)?;
                previous = Some(key);
            }
            postings.push(manifest, postings.count as u128, vec![id])?;
        }
        postings.finish(manifest)?;
    }
    keys.finish().map_err(fst_error)?;
    ensure(
        fs::metadata(&file)?.len() <= container::MAX_SHARD_BYTES as u64 - 128,
        "Forward FST exceeds shard limit",
    )?;
    add(
        stage,
        manifest,
        "keys.bin",
        "keys",
        &container::encode(11, &[(&fs::read(&file)?, 1)])?,
    )?;
    fs::remove_file(file)?;
    Ok(count)
}
fn validate_airport_identity(db: &Connection) -> Result<()> {
    for field in [
        "country",
        "state",
        "city",
        "latitude",
        "longitude",
        "name",
        "details",
    ] {
        let sql = format!(
            "SELECT EXISTS(SELECT 1 FROM observations GROUP BY source,source_id HAVING MIN({field})<>MAX({field}) OR (COUNT({field})>0 AND COUNT({field})<COUNT(*)))"
        );
        let conflicts: bool = db.query_row(&sql, [], |r| r.get(0))?;
        ensure(
            !conflicts,
            "Airport source identity has conflicting records",
        )?;
    }
    Ok(())
}
#[allow(clippy::needless_pass_by_value)]
fn fst_error(error: fst::Error) -> Error {
    Error::Input(format!("Cannot encode sorted keys: {error}"))
}
