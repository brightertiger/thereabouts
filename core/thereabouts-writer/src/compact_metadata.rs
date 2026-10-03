//! Forward metadata contains only referenced projection fields, never provenance.
use crate::Result;
use rusqlite::Connection;
use std::collections::BTreeSet;
use thereabouts_core::format::metadata::Metadata;
pub(crate) fn trim(db: &Connection, metadata: &mut Metadata) -> Result<()> {
    let mut countries = BTreeSet::new();
    let mut subdivisions = BTreeSet::new();
    let mut query =
        db.prepare("SELECT p.country_code,p.code,p.role FROM places p JOIN ids USING(id)")?;
    for row in query.query_map([], |r| {
        Ok((
            r.get::<_, Option<String>>(0)?,
            r.get::<_, Option<String>>(1)?,
            r.get::<_, String>(2)?,
        ))
    })? {
        let (country, code, role) = row?;
        countries.extend(country);
        if role == "state" {
            subdivisions.extend(code);
        }
    }
    metadata.countries.retain(|r| {
        r["country_code"]
            .as_str()
            .is_some_and(|c| countries.contains(c))
    });
    metadata
        .subdivisions
        .retain(|r| r["code"].as_str().is_some_and(|c| subdivisions.contains(c)));
    strip(metadata);
    Ok(())
}
fn strip(metadata: &mut Metadata) {
    for (rows, fields) in [
        (
            &mut metadata.countries,
            &["country_code", "alpha3", "name"][..],
        ),
        (
            &mut metadata.subdivisions,
            &["code", "country_code", "name"][..],
        ),
    ] {
        for row in rows {
            if let Some(object) = row.as_object_mut() {
                object.retain(|k, _| fields.contains(&k.as_str()));
            }
        }
    }
    metadata.zone_tables.clear();
    metadata.timezone_sets = vec![vec![]];
}

/// Every country is referenced by the country-hint API, even without a format rule.
pub(crate) fn plate(metadata: &mut Metadata, tables: &thereabouts_core::format::plates::Tables) {
    let codes = tables
        .codes
        .iter()
        .flat_map(|c| c.subdivision_codes.iter())
        .collect::<BTreeSet<_>>();
    metadata.subdivisions.retain(|r| {
        r["code"]
            .as_str()
            .is_some_and(|c| codes.iter().any(|v| v.as_str() == c))
    });
    strip(metadata);
}
