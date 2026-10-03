//! Bounded name-index staging; future alternate-name tables feed the same index.
use crate::{
    Error, Result, add, catalogue, error::ensure, geography::geography, inserts::Inserts,
    source::Dataset,
};
use rusqlite::{Connection, types::Value};
use std::path::Path;
use thereabouts_core::{
    format::{
        manifest::Manifest,
        names::{Entry, encode_entries},
    },
    name_normalization::{Policy, normalize},
};
// Matches the forward writer's 4 MiB input batches; leaves room for both FST
// builders and Unicode trigram postings inside the shared 512 MiB admission budget.
const NAME_INPUT_BYTES: usize = 4 * 1024 * 1024;
pub(crate) fn emit(
    data: &Dataset,
    db: &Connection,
    stage: &Path,
    manifest: &mut Manifest,
) -> Result<()> {
    let policy = manifest
        .name_normalization
        .as_ref()
        .ok_or_else(|| Error::Input("Missing name normalization policy".into()))?;
    db.execute_batch("CREATE TABLE names(key TEXT,city TEXT,name TEXT,alternate INTEGER,PRIMARY KEY(key,city,name,alternate)) WITHOUT ROWID")?;
    let mut inserts = Inserts::new(db, "INSERT OR IGNORE INTO names", 4);
    {
        let mut query = db.prepare("SELECT id,name,name_en FROM cities ORDER BY id")?;
        for row in query.query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, Option<String>>(2)?,
            ))
        })? {
            let (id, primary, english) = row?;
            let primary =
                primary.ok_or_else(|| Error::Input("Canonical city lacks a name".into()))?;
            insert(&mut inserts, &id, &primary, false, policy)?;
            if let Some(name) = english {
                insert(&mut inserts, &id, &name, true, policy)?;
            }
        }
    }
    for table in data.tables("names") {
        data.scan(table, |row| {
            let kind = row.required("kind")?;
            ensure(
                matches!(kind, "primary" | "english" | "alternate" | "ascii"),
                "Unknown city-name kind",
            )?;
            let id = row.required("city_id")?;
            let exists: bool = db.query_row(
                "SELECT EXISTS(SELECT 1 FROM cities WHERE id=?)",
                [id],
                |r| r.get(0),
            )?;
            ensure(exists, "Name references a noncanonical city")?;
            insert(
                &mut inserts,
                id,
                row.required("name")?,
                kind != "primary",
                policy,
            )
        })?;
    }
    inserts.flush()?;
    output(db, stage, manifest)
}
fn insert(
    rows: &mut Inserts<'_>,
    city: &str,
    name: &str,
    alternate: bool,
    policy: &Policy,
) -> Result<()> {
    let key = normalize(name, policy);
    ensure(
        !key.is_empty() && key.chars().count() <= 128,
        "City name exceeds normalized length limit",
    )?;
    rows.push([
        Value::Text(key),
        Value::Text(city.into()),
        Value::Text(name.into()),
        Value::Integer(i64::from(alternate)),
    ])
}
fn output(db: &Connection, stage: &Path, manifest: &mut Manifest) -> Result<()> {
    let mut query=db.prepare("SELECT key,city,name,alternate FROM names ORDER BY key COLLATE BINARY,city COLLATE BINARY,alternate,name COLLATE BINARY")?;
    let mut entries = Vec::new();
    let mut size = 0;
    let mut shard = 0;
    for row in query.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, String>(2)?,
            r.get::<_, bool>(3)?,
        ))
    })? {
        let (key, city, name, alternate) = row?;
        let place = catalogue::record(db, &city)?;
        let mut places = geography(db, place.refs[0], &city)?;
        // Canonical cities are already final; keep their published identity.
        places[2] = catalogue::reference(db, Some(&city))?;
        let bytes = key.len() + name.len() + 128;
        if size + bytes > NAME_INPUT_BYTES && !entries.is_empty() {
            add(
                stage,
                manifest,
                &format!("names-{shard:05}.bin"),
                "names",
                &encode_entries(&entries)?,
            )?;
            entries.clear();
            size = 0;
            shard += 1;
        }
        size += bytes;
        entries.push((
            key,
            Entry {
                places,
                name,
                alternate,
            },
        ));
    }
    add(
        stage,
        manifest,
        &format!("names-{shard:05}.bin"),
        "names",
        &encode_entries(&entries)?,
    )
}
